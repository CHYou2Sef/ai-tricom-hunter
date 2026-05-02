"""
Layer 0 — Ingest LangGraph
Replaces the raw watchdog loop in run/ingest.py with a structured
LangGraph state machine that validates, cleans, classifies, chunks,
routes, archives, and emits every incoming file.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional
from pathlib import Path

from core import config
from core.logger import get_logger
from .state import Layer0State

logger = get_logger(__name__)

# ── Module-level singletons ──────────────────────────────────────────
_graph: Optional[object]            = None   # compiled LangGraph (lazy init)
_l1_queue: Optional[asyncio.Queue] = None   # injected by supervisor.py


def set_l1_queue(q: asyncio.Queue) -> None:
    """
    Called once by supervisor.py at startup.
    Injects the shared asyncio.Queue so emit_event_node can push
    classified file paths to the Layer 1 consumer.
    """
    global _l1_queue
    _l1_queue = q


def _get_l1_queue() -> Optional[asyncio.Queue]:
    """Read-only accessor used by emit_event_node."""
    return _l1_queue


def _get_graph():
    """Lazy-compile the LangGraph once; return the singleton thereafter."""
    global _graph
    if _graph is None:
        from .graph import build_layer0_graph
        _graph = build_layer0_graph()
        logger.debug("[Layer0] Graph compiled and cached.")
    return _graph


def process_incoming_file(file_path: str) -> Layer0State:
    """
    Synchronous entry point: run the Layer 0 graph for one file.

    Called from the watchdog thread (IngestHandler._handle in supervisor.py).
    The graph is CPU-bound + I/O via httpx/shutil, so running it synchronously
    in the watchdog thread is fine — it doesn't block the asyncio event loop.

    Args:
        file_path: Absolute path to the file that landed in INCOMING/.

    Returns:
        Final Layer0State after the graph completes.
    """
    p = Path(file_path)

    initial: Layer0State = {
        "raw_file_path":   str(p),
        "file_name":       p.name,
        "file_ext":        p.suffix.lower(),
        "is_valid_format": False,
        "row_count":       0,
        "error_reason":    None,
        "row_type":        "UNKNOWN",
        "chunk_paths":     [],
        "routed_paths":    [],
        "archived_path":   None,
        "final_status":    "NOT_STARTED",
        "emitted_events":  [],
    }

    try:
        from common.metrics import get_layer_telemetry
        telemetry = get_layer_telemetry()
        start_ts = time.time()

        graph = _get_graph()
        # thread_id is used by MemorySaver for checkpointing
        final: Layer0State = graph.invoke(
            initial,
            config={"configurable": {"thread_id": p.stem}},
        )

        duration = time.time() - start_ts
        success = final.get("final_status") == "ROUTED"
        telemetry.record(
            "Layer 0", 
            success, 
            duration, 
            files_emitted=len(final.get("emitted_events", [])),
            rows=final.get("row_count", 0)
        )
        telemetry.save_to_json()

        logger.info(
            f"[Layer 0] ✅ Processing complete for {p.name} → Status: {final.get('final_status')} "
            f"({len(final.get('emitted_events', []))} chunk(s) emitted to Layer 1 queue) | {duration:.2f}s"
        )
        return final

    except Exception as exc:
        logger.error(f"[Layer0] Graph error for {p.name}: {exc}", exc_info=True)
        return {**initial, "final_status": "ERROR", "error_reason": str(exc)}
