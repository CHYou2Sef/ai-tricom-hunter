"""
Layer 0 — Ingest State Schema
TypedDict that carries all data through the ingest LangGraph.
"""
from __future__ import annotations
from typing import TypedDict, Optional, List


class Layer0State(TypedDict):
    # ── Input ──────────────────────────────────────────────────────
    raw_file_path:    str             # absolute path dropped into INCOMING/
    file_name:        str
    file_ext:         str

    # ── Validation ────────────────────────────────────────────────
    is_valid_format:  bool
    row_count:        int
    error_reason:     Optional[str]  # populated if invalid

    # ── Classification ────────────────────────────────────────────
    row_type:         str            # "STD" | "RS" | "SIREN" | "OTHER"
    chunk_paths:      List[str]      # file paths after chunking
    routed_paths:     List[str]      # final paths in STD/, RS/, etc.

    # ── Outcome ───────────────────────────────────────────────────
    archived_path:    Optional[str]
    final_status:     str            # "ROUTED" | "QUARANTINED" | "EMPTY" | "ERROR"
    emitted_events:   List[str]      # file paths pushed to Layer 1 queue
