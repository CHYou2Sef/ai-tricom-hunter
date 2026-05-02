"""
Layer 0 — Ingest LangGraph Graph Definition

Graph flow (happy path):
  validate_file → clean_data → classify → chunk
               → route_to_bucket → archive → emit_event → END

Error path:
  validate_file → quarantine → END

The MemorySaver checkpointer persists state per thread_id (file stem).
Swap it for SqliteSaver / RedisSaver for true cross-process persistence.
"""
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.memory import MemorySaver

from .state import Layer0State
from .nodes import (
    validate_file_node,
    clean_data_node,
    classify_node,
    chunk_node,
    route_to_bucket_node,
    archive_node,
    quarantine_node,
    emit_event_node,
)


def build_layer0_graph():
    """Build and compile the Layer 0 ingest state machine."""
    g = StateGraph(Layer0State)

    # ── Register nodes ────────────────────────────────────────────
    g.add_node("validate_file",   validate_file_node)
    g.add_node("clean_data",      clean_data_node)
    g.add_node("classify",        classify_node)
    g.add_node("chunk",           chunk_node)
    g.add_node("route_to_bucket", route_to_bucket_node)
    g.add_node("archive",         archive_node)
    g.add_node("quarantine",      quarantine_node)
    g.add_node("emit_event",      emit_event_node)

    # ── Entry point ───────────────────────────────────────────────
    g.set_entry_point("validate_file")

    # ── Conditional: valid file → clean | invalid → quarantine ────
    g.add_conditional_edges(
        "validate_file",
        lambda s: "clean_data" if s["is_valid_format"] else "quarantine",
        {
            "clean_data": "clean_data",
            "quarantine": "quarantine",
        },
    )

    # ── Quarantine is a terminal node ─────────────────────────────
    g.add_edge("quarantine", END)

    # ── Conditional: non-empty → classify | empty → END ──────────
    g.add_conditional_edges(
        "clean_data",
        lambda s: "classify" if s["row_count"] > 0 else END,
        {"classify": "classify", END: END},
    )

    # ── Linear happy path ─────────────────────────────────────────
    g.add_edge("classify",        "chunk")
    g.add_edge("chunk",           "route_to_bucket")
    g.add_edge("route_to_bucket", "archive")
    g.add_edge("archive",         "emit_event")
    g.add_edge("emit_event",      END)

    # ── Compile with in-memory checkpointer ──────────────────────
    # Swap MemorySaver → SqliteSaver(db_path) for crash-resilient 24/7 mode
    checkpointer = MemorySaver()
    return g.compile(checkpointer=checkpointer)
