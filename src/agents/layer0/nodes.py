"""
Layer 0 — Ingest LangGraph Node Functions

All nodes are pure functions: (Layer0State) -> Layer0State.
They wrap the existing domain logic (read_excel, clean_and_classify, FileChunker)
so the graph is just an orchestrator — no business logic lives here.
"""
import os
import shutil
import time
from pathlib import Path

from .state import Layer0State
from core import config
from core.logger import get_logger

logger = get_logger(__name__)


# ── Node 1: Validate incoming file ──────────────────────────────────────
def validate_file_node(state: Layer0State) -> Layer0State:
    """
    Reject hidden/lock files and unsupported extensions early.
    Sets is_valid_format=True only for accepted, existing files.
    """
    path = Path(state["raw_file_path"])
    name = path.name

    if name.startswith((".", "~")):
        return {**state, "is_valid_format": False, "error_reason": "hidden_or_lock_file"}

    if path.suffix.lower() not in config.ACCEPTED_EXTENSIONS:
        return {**state, "is_valid_format": False, "error_reason": f"unsupported_extension:{path.suffix}"}

    if not path.exists():
        return {**state, "is_valid_format": False, "error_reason": "file_not_found"}

    logger.info(f"[L0|validate] ✅ {name}")
    return {
        **state,
        "is_valid_format": True,
        "file_name":       name,
        "file_ext":        path.suffix.lower(),
    }


# ── Node 2: Read & count rows ────────────────────────────────────────────
def clean_data_node(state: Layer0State) -> Layer0State:
    """
    Read rows from file and count them.
    Actual column cleaning/classification happens inside classify_node.
    """
    from domain.excel.reader import read_excel

    rows, _ = read_excel(state["raw_file_path"])
    count   = len(rows)
    if count == 0:
        logger.warning(f"[L0|clean] ⚠️  Empty file: {state['file_name']}")
        return {**state, "row_count": 0, "final_status": "EMPTY"}

    logger.info(f"[L0|clean] {count} rows read from {state['file_name']}")
    return {**state, "row_count": count}


# ── Node 3: Classify rows into buckets ──────────────────────────────────
def classify_node(state: Layer0State) -> Layer0State:
    """
    Delegate to existing clean_and_classify() which writes output files
    into STD/, RS/, SIREN/, OTHERS/ buckets.  No new logic needed here.
    """
    from domain.excel.reader import read_excel
    from domain.excel.cleaner import clean_and_classify

    rows, _ = read_excel(state["raw_file_path"])
    headers = list(rows[0].raw.keys()) if rows else []
    stats   = clean_and_classify(rows, state["raw_file_path"], headers)
    logger.info(f"[L0|classify] Stats: {stats}")
    return state  # clean_and_classify writes output directly


# ── Node 4: Chunk large files ────────────────────────────────────────────
def chunk_node(state: Layer0State) -> Layer0State:
    """
    Split large files using the existing FileChunker.
    If the file is small enough, FileChunker returns the original path.
    """
    from common.chunker import FileChunker

    chunker = FileChunker()
    chunks  = chunker.split_file(state["raw_file_path"])
    paths   = [str(c) for c in chunks if Path(c).exists()]
    logger.info(f"[L0|chunk] {len(paths)} chunk(s) produced")
    return {**state, "chunk_paths": paths}


# ── Node 5: Record routed file paths ────────────────────────────────────
def route_to_bucket_node(state: Layer0State) -> Layer0State:
    """
    Scan output buckets for files matching our source file stem.
    clean_and_classify() already placed them; we just record paths.
    """
    stem    = Path(state["raw_file_path"]).stem
    buckets = [
        config.INPUT_STD_DIR,
        config.INPUT_RS_DIR,
        config.INPUT_SIR_DIR,
        config.INPUT_OTHER_DIR,
    ]
    routed = []
    for bucket in buckets:
        if not Path(bucket).exists():
            continue
        for f in Path(bucket).iterdir():
            if stem in f.name and f.suffix.lower() in config.ACCEPTED_EXTENSIONS:
                routed.append(str(f))

    logger.info(f"[L0|route] {len(routed)} file(s) routed to buckets")
    return {**state, "routed_paths": routed, "final_status": "ROUTED"}


# ── Node 6: Archive original file ───────────────────────────────────────
def archive_node(state: Layer0State) -> Layer0State:
    """
    Move the original INCOMING file to ARCHIVE/BACKUP.
    Handles filename collisions with a timestamp prefix.
    """
    from common.fs import safe_mkdir

    src  = Path(state["raw_file_path"])
    if not src.exists():
        logger.debug(f"[L0|archive] Source already moved: {src.name}")
        return state  # chunker may have consumed it already

    safe_mkdir(config.ARCHIVE_BACKUP_DIR)
    dest = Path(config.ARCHIVE_BACKUP_DIR) / src.name
    if dest.exists():
        ts   = time.strftime("%Y%m%d_%H%M%S")
        dest = Path(config.ARCHIVE_BACKUP_DIR) / f"{ts}_{src.name}"

    shutil.move(str(src), str(dest))
    logger.info(f"[L0|archive] → {dest.name}")
    return {**state, "archived_path": str(dest)}


# ── Node 7: Quarantine invalid files ────────────────────────────────────
def quarantine_node(state: Layer0State) -> Layer0State:
    """
    Move invalid / malformed files to WORK/QUARANTINE/ for human review.
    Never silently deletes — always preserves the original for inspection.
    """
    from common.fs import safe_mkdir

    q_dir = Path(config.WORK_DIR) / "QUARANTINE"
    safe_mkdir(q_dir)

    src = Path(state["raw_file_path"])
    if src.exists():
        dest = q_dir / src.name
        if dest.exists():
            ts   = time.strftime("%Y%m%d_%H%M%S")
            dest = q_dir / f"{ts}_{src.name}"
        shutil.move(str(src), str(dest))

    logger.warning(
        f"[L0|quarantine] {state['file_name']} → QUARANTINE "
        f"(reason: {state.get('error_reason', 'unknown')})"
    )
    return {**state, "final_status": "QUARANTINED"}


# ── Node 8: Emit file events to Layer 1 queue ───────────────────────────
def emit_event_node(state: Layer0State) -> Layer0State:
    """
    Push all routed file paths onto the shared asyncio.Queue
    that the Layer 1 consumer (supervisor.py) listens to.

    The queue reference is injected at startup by set_l1_queue().
    Nodes remain pure functions — they read from a module singleton.
    """
    from agents.layer0 import _get_l1_queue

    queue = _get_l1_queue()
    emitted = []

    for path in state.get("routed_paths", []):
        if Path(path).exists():
            if queue is not None:
                queue.put_nowait(path)
            emitted.append(path)
            logger.info(f"[L0|emit] 📤 → Layer 1 queue: {Path(path).name}")

    return {**state, "emitted_events": emitted}
