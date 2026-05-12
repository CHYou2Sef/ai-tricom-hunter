#!/usr/bin/env python3
import argparse
import asyncio
import os
import shutil
import sys
import tempfile
from pathlib import Path

# Ensure project root is on sys.path; scripts may be executed from repo root or elsewhere.
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "src") not in sys.path:
    sys.path.insert(0, str(ROOT / "src"))

# Must be first import for sys.path/websockets shims.
# Avoid module-resolution issues by loading bootstrap.py directly from repo root.
import importlib.util as _importlib_util

_bootstrap_path = ROOT / "bootstrap.py"
_spec = _importlib_util.spec_from_file_location("bootstrap", _bootstrap_path)
if _spec is None or _spec.loader is None:
    raise SystemExit(f"Unable to load bootstrap.py from: {_bootstrap_path}")
_bootstrap = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_bootstrap)  # type: ignore[union-attr]

from app.orchestrator import init_agent_pool, close_agent_pool, process_file_async
from core import config
from domain.excel.reader import read_excel
from domain.excel.writer import save_subset_to_excel

from core.logger import get_logger

logger = get_logger(__name__)


def _find_row(rows, row_index: int):
    # ExcelRow.row_index is the original row number in the sheet (1-based typically).
    # Also allow selecting by 0-based positional index as a fallback.
    for r in rows:
        if getattr(r, "row_index", None) == row_index:
            return r
    if 0 <= row_index < len(rows):
        return rows[row_index]
    return None


async def main():
    parser = argparse.ArgumentParser(description="Run critical-path pipeline for a single selected row.")
    parser.add_argument("--incoming", required=True, help="Path to a file inside INCOMING/ (or any supported excel/csv/json).")
    parser.add_argument("--row-index", type=int, required=True, help="ExcelRow.row_index to run (tries exact match, else 0-based positional).")
    parser.add_argument("--max-workers", type=int, default=None, help="Override config.MAX_CONCURRENT_WORKERS for the run.")
    parser.add_argument("--tmp-dir", type=str, default=None, help="Optional temp directory for the subset file.")
    args = parser.parse_args()

    incoming_path = Path(args.incoming)
    if not incoming_path.exists():
        raise SystemExit(f"Incoming file not found: {incoming_path}")

    tmp_dir = Path(args.tmp_dir) if args.tmp_dir else Path(tempfile.mkdtemp(prefix="single_row_"))
    tmp_dir.mkdir(parents=True, exist_ok=True)

    # Read and extract a single row
    logger.info(f"[single-row] Reading input: {incoming_path}")
    rows, _ = await asyncio.to_thread(read_excel, str(incoming_path))
    if not rows:
        raise SystemExit(f"No rows found in input: {incoming_path}")

    row = _find_row(rows, args.row_index)
    if row is None:
        raise SystemExit(f"Row index {args.row_index} not found in parsed rows (total={len(rows)}).")

    subset_path = tmp_dir / incoming_path.name
    logger.info(f"[single-row] Writing subset (1 row) to: {subset_path}")
    save_subset_to_excel([row], subset_path)

    # Optionally override concurrency
    if args.max_workers is not None:
        config.MAX_CONCURRENT_WORKERS = int(args.max_workers)

    # Pre-warm agent pool with conservative size (same as MAX_CONCURRENT_WORKERS)
    await init_agent_pool(config.MAX_CONCURRENT_WORKERS)

    # Run the normal file processor against the 1-row subset
    try:
        logger.info(f"[single-row] Starting orchestrator on subset file: {subset_path.name}")
        await process_file_async(str(subset_path))
    finally:
        await close_agent_pool()

    logger.info(f"[single-row] Completed. Subset file remains at: {subset_path}")


if __name__ == "__main__":
    asyncio.run(main())
