"""
╔══════════════════════════════════════════════════════════════════════════╗
║  app/orchestrator.py  —  Core Orchestration Engine                       ║
║                                                                          ║
║  Role: Central dispatcher.  Manages an async pool of browser workers,    ║
║  routes each row to PhoneHunter then Enricher, and handles persistence. ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import random
import asyncio
from typing import List, Optional
from pathlib import Path
import pandas as pd

from core import config
from domain.excel.reader import ExcelRow, read_excel
from domain.excel.writer import save_results, save_subset_to_excel
from core.logger import get_logger
from common.metrics import PerformanceTracker, get_telemetry
from common.progress_tracker import FileProgressTracker
from domain.search.phone_extractor import normalize_phone

# Canonical Agent Imports
from agents.phone_hunter import process_row
from agents.enricher import enrich_row

logger = get_logger(__name__)

# ── Agent Pool ───────────────────────────────────────────────────────────
# asyncio.Queue gives us a cheap semaphore-like pool of pre-warmed browsers.
_agent_pool = asyncio.Queue()

async def init_agent_pool(count: int):
    """
    Pre-warm `count` HybridAutomationEngine instances.
    Each worker starts on the default tier so the first row is fast.
    """
    logger.info(f"[AgentPool] Initializing {count} workers...")
    for i in range(count):
        from infra.browsers.hybrid_engine import HybridAutomationEngine
        agent = HybridAutomationEngine(worker_id=i+1)
        await agent.start_tier(config.HYBRID_DEFAULT_TIER)
        await _agent_pool.put(agent)

async def close_agent_pool():
    """Gracefully close every agent in the pool to free RAM / sockets."""
    while not _agent_pool.empty():
        agent = await _agent_pool.get()
        await agent.close()

def sync_with_previous_results(rows: List[ExcelRow], filepath: str, progress: FileProgressTracker) -> int:
    """
    Resume interrupted runs by checking two sources:
      1. Per-file JSON checkpoint (fast, local)
      2. Daily fusion Excel (global dedup)
    A row is only considered DONE if the checkpoint actually stores a phone.
    """
    import datetime
    orig_path = Path(filepath)
    input_folder = orig_path.parent.name
    out_dir = config.get_output_dir(input_folder)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    fusion_path = out_dir / f"{input_folder}_{date_str}.xlsx"
    
    # 1. Load Fusion Data for real-value synchronization
    existing_data = {}
    if fusion_path.exists():
        try:
            df_sync = pd.read_excel(fusion_path, dtype=str)
            if "__fingerprint" in df_sync.columns:
                # Create a lookup map: fingerprint -> (phone, agent_phone)
                for _, row_data in df_sync.iterrows():
                    fp = row_data["__fingerprint"]
                    if pd.notna(fp):
                        existing_data[fp] = {
                            "phone": row_data.get("AI_Phone"),
                            "agent_phone": row_data.get("AI_Agent_Phone")
                        }
        except Exception as e:
            logger.warning(f"[Agent] Failed to read fusion file for sync: {e}")

    sync_count = 0

    for r in rows:
        fp = r.get_fingerprint()
        
        # Priority 1: Check File-Specific Checkpoint (NEW)
        cp_data = progress.get_row_data(r.row_index)
        if cp_data:
            valid_p = normalize_phone(cp_data.get("phone"))
            valid_a = normalize_phone(cp_data.get("agent_phone"))
            status = cp_data.get("status")
            
            # H3 fix: LOW_CONF (SIREN mismatch) is a terminal state — don't re-process
            if valid_p or valid_a or status in ["DONE", "NO TEL", "SKIP", "LOW_CONF"]:
                r.phone = valid_p
                r.agent_phone = valid_a
                r.status = status or "DONE"
                # Restore all other enriched information
                for k, v in cp_data.items():
                    if k not in ["phone", "agent_phone", "status"]:
                        r.enriched_fields[k] = v
                sync_count += 1
                continue

        # Priority 2: Check if already in Daily Fusion (Global Sync)
        if fp in existing_data:
            res = existing_data[fp]
            valid_p = normalize_phone(res.get("phone")) if pd.notna(res.get("phone")) else None
            valid_a = normalize_phone(res.get("agent_phone")) if pd.notna(res.get("agent_phone")) else None
            
            if valid_p or valid_a:
                r.phone = valid_p
                r.agent_phone = valid_a
                r.status = "DONE"
                sync_count += 1
                continue
            
    if sync_count > 0:
        logger.info(f"[Agent] 🔄 Synced {sync_count} rows from checkpoint/fusion. Resuming...")
        
    return sync_count

from dataclasses import dataclass

@dataclass
class WorkerContext:
    """
    Immutable-ish bag of dependencies for one row.
    Passed through the coroutine chain so every layer has
    access to locks, trackers, and the shared row list.
    """
    row: ExcelRow
    sem: asyncio.Semaphore
    save_lock: asyncio.Lock
    all_rows: List[ExcelRow]
    filepath: str
    tracker: PerformanceTracker
    idx: int
    total: int
    progress: FileProgressTracker

async def _execute_agent_task(ctx: WorkerContext, agent) -> None:
    """
    Run the two-phase pipeline for one row:
      1. Phone extraction (if missing)
      2. Enrichment      (if enabled and phone found)
    Writes the result atomically to the JSON checkpoint so crashes
    do not lose progress.
    """
    if not ctx.row.phone:
        await process_row(ctx.row, agent)
    if ctx.row.phone and getattr(config, 'ENRICH_ENABLED', False):
        await enrich_row(ctx.row, agent)
    
    # Atomic checkpoint: survives sudden SIGKILL / power loss
    ctx.progress.mark_row_done(
        ctx.row.row_index, 
        ctx.row.phone, 
        ctx.row.agent_phone, 
        ctx.row.status,
        extra=ctx.row.enriched_fields
    )

    # 🎭 [Human Noise] Trigger session seasoning occasionally
    if getattr(config, 'ENABLE_HUMAN_NOISE', False):
        if ctx.row.row_index % config.HUMAN_NOISE_INTERVAL == 0:
            try:
                # Get the active browser engine from the hybrid engine if possible
                # or just use the current agent
                await agent.generate_human_noise()
            except Exception as e:
                logger.debug(f"[Orchestrator] Noise generation failed: {e}")

async def _worker_process_row(ctx: WorkerContext):
    """
    Coroutine executed by each pool worker.
    Handles agent checkout → health check → task → checkin → save.
    """
    async with ctx.sem:   # Limits concurrent browsers (RAM/CPU bound)
        row_start = time.perf_counter()
        agent = None
        try:
            agent = await _agent_pool.get()
            
            # P0 Fix: Agents can die (Chrome crash, proxy hang).  Verify before use.
            if hasattr(agent, 'is_alive') and not await agent.is_alive():
                logger.warning(f"[AgentPool] Worker dead, recreating...")
                await agent.close()
                from infra.browsers.hybrid_engine import HybridAutomationEngine
                agent = HybridAutomationEngine(worker_id=getattr(agent, 'worker_id', ctx.idx))
                await agent.start_tier(config.HYBRID_DEFAULT_TIER)
            
            await _execute_agent_task(ctx, agent)
            
        except Exception as e:
            logger.error(f"[Agent] Error on row {ctx.row.row_index}: {e}")
            ctx.row.status = "ERROR"
        finally:
            if agent:
                # Recycle healthy agents; dead ones are left for GC
                await _agent_pool.put(agent)
        
        elapsed = time.perf_counter() - row_start
        ctx.tracker.track_row(elapsed, ctx.row.status)
        
        # Periodic disk flush (trade-off: safety vs I/O load on HDD)
        if ctx.idx % config.SAVE_INTERVAL == 0 or ctx.idx == ctx.total:
            async with ctx.save_lock:
                await asyncio.to_thread(save_results, ctx.all_rows, ctx.filepath)
    return ctx.row

async def process_file_async(filepath: str) -> None:
    """
    End-to-end async file processor.
    Flow: read → resume → filter → parallel worker dispatch → save → archive.
    """
    logger.info(f"[Agent] Starting file: {os.path.basename(filepath)}")
    rows, _ = await asyncio.to_thread(read_excel, filepath)
    if not rows: return

    # Checkpoint file: keeps partial progress across crashes
    progress = FileProgressTracker(filepath)

    # Proactive cleanup so we don't run out of disk during long runs
    from common.disk_cleanup import check_and_cleanup
    check_and_cleanup()

    tracker = PerformanceTracker()
    tracker.start_file_processing()
    await asyncio.to_thread(sync_with_previous_results, rows, filepath, progress)
    
    # Decide which rows still need work
    # LOW_CONF = SIREN mismatch — terminal state, no re-processing
    terminal = ("DONE", "NO TEL", "SKIP", "LOW_CONF")
    rows_to_process = (
        [r for r in rows if r.status != "DONE"] if config.REPROCESS_FAILED_ROWS
        else [r for r in rows if r.status not in terminal]
    )
    total = len(rows_to_process)
    
    if total == 0:
        logger.info(f"[Agent] ⏭️  Skipping '{os.path.basename(filepath)}' — 0 rows to process.")
    else:
        logger.info(f"[Agent] 🔄 Processing {total} rows from '{os.path.basename(filepath)}'...")
        save_lock = asyncio.Lock()                 # Serialises Excel writes
        sem = asyncio.Semaphore(config.MAX_CONCURRENT_WORKERS)  # RAM/CPU guard
        tasks = []
        for i, r in enumerate(rows_to_process, 1):
            ctx = WorkerContext(
                row=r, sem=sem, save_lock=save_lock, all_rows=rows, 
                filepath=filepath, tracker=tracker, idx=i, total=total, progress=progress
            )
            tasks.append(asyncio.create_task(_worker_process_row(ctx)))
        await asyncio.gather(*tasks)
    
    # Final flush and archival
    await asyncio.to_thread(save_results, rows, filepath, force=True)
    tracker.end_file_processing()
    await finalize_file_processing(rows, filepath, tracker, progress)
    
    get_telemetry().finalize()

async def finalize_file_processing(
    rows: List[ExcelRow], original_filepath: str, tracker: Optional[PerformanceTracker] = None, progress: FileProgressTracker = None
) -> None:
    orig_path = Path(original_filepath)
    success_rows  = [r for r in rows if r.status == "DONE"]
    low_conf_rows = [r for r in rows if r.status == "LOW_CONF"]
    retry_rows    = [r for r in rows if r.status in ("NO TEL", "SKIP", "PENDING", "ERROR")]

    total = len(rows)
    duration_str = f"{tracker.get_metrics_summary()['total_execution_seconds']}s" if tracker else "N/A"

    logger.info("")
    logger.info(f"{'━' * 60}")
    logger.info(f"📊  FILE COMPLETED: {orig_path.name}")
    logger.info(f"   📁 Total: {total} | ⏱️ Duration: {duration_str}")
    logger.info(f"   ✅ DONE: {len(success_rows)} | ⚠️  LOW_CONF: {len(low_conf_rows)} | 🔁 Retry: {len(retry_rows)}")
    logger.info(f"{'━' * 60}")

    if success_rows:
        target = config.OUTPUT_SUCCEED_DIR / orig_path.name
        await asyncio.to_thread(save_subset_to_excel, success_rows, target)
        logger.info(f"   💾 Saved to SUCCEED/ folder")
    
    if retry_rows:
        target = config.OUTPUT_FAILED_DIR / orig_path.name
        await asyncio.to_thread(save_subset_to_excel, retry_rows, target)
        logger.info(f"   🔁 Saved to FAILED/ folder")

    if progress:
        progress.archive()
    try: os.remove(original_filepath)
    except: pass
