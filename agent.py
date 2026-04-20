"""
╔══════════════════════════════════════════════════════════════════════════╗
║  agent.py  —  Core Orchestration Engine (Canonical Layout)               ║
║                                                                          ║
║  This file acts as the ORCHESTRATOR. It manages the pool of agents       ║
║  and routes logic to Specialized Agents (PhoneHunter, Enricher).         ║
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

import config
from excel.reader import ExcelRow, read_excel
from excel.writer import save_results, save_subset_to_excel
from utils.logger import get_logger
from utils.metrics import PerformanceTracker
from utils.progress_tracker import FileProgressTracker
from search.phone_extractor import normalize_phone

# Canonical Agent Imports
from agents.phone_hunter import process_row
from agents.enricher import enrich_row

logger = get_logger(__name__)

# Agent Pool for parallel workers
_agent_pool = asyncio.Queue()

async def init_agent_pool(count: int):
    """Pre-initialize a pool of browser hybrid engines."""
    logger.info(f"[AgentPool] Initializing {count} workers...")
    for i in range(count):
        from browser.hybrid_engine import HybridAutomationEngine
        agent = HybridAutomationEngine(worker_id=i+1)
        await agent.start_tier(config.HYBRID_DEFAULT_TIER)
        await _agent_pool.put(agent)

async def close_agent_pool():
    """Close all workers in the pool."""
    while not _agent_pool.empty():
        agent = await _agent_pool.get()
        await agent.close()

def sync_with_previous_results(rows: List[ExcelRow], filepath: str, progress: FileProgressTracker) -> int:
    """
    Synchronize with today's previous results using Pandas.
    Ensures data integrity: a row is only 'DONE' if we actually have its result data.
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
            
            # If we have data OR a definitive finish status, sync it
            if valid_p or valid_a or status in ["DONE", "NO TEL", "SKIP"]:
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

async def _worker_process_row(row, sem, save_lock, rows, filepath, tracker, idx, total, progress):
    async with sem:
        row_start = time.perf_counter()
        agent = None
        try:
            agent = await _agent_pool.get()
            
            # P0 Fix #1: Health check before use
            if hasattr(agent, 'is_alive') and not await agent.is_alive():
                logger.warning(f"[AgentPool] Worker dead, recreating...")
                await agent.close()
                from browser.hybrid_engine import HybridAutomationEngine
                agent = HybridAutomationEngine(worker_id=getattr(agent, 'worker_id', idx))
                await agent.start_tier(config.HYBRID_DEFAULT_TIER)
            
            extra_phones = []
            if not row.phone:
                extra_phones = await process_row(row, agent)
            if row.phone and hasattr(config, 'ENRICH_ENABLED') and config.ENRICH_ENABLED:
                await enrich_row(row, agent)
            
            # Atomic Save to per-file JSON tracker
            progress.mark_row_done(
                row.row_index, 
                row.phone, 
                row.agent_phone, 
                row.status,
                extra=row.enriched_fields
            )
        except Exception as e:
            logger.error(f"[Agent] Error on row {row.row_index}: {e}")
            row.status = "ERROR"
        finally:
            if agent:
                # Keep it alive if possible, or close if dead
                await _agent_pool.put(agent)
        
        elapsed = time.perf_counter() - row_start
        tracker.track_row(elapsed, row.status)
        
        if idx % config.SAVE_INTERVAL == 0 or idx == total:
            async with save_lock:
                await asyncio.to_thread(save_results, rows, filepath)
    return row

async def process_file_async(filepath: str) -> None:
    logger.info(f"[Agent] Starting file: {os.path.basename(filepath)}")
    rows, _ = await asyncio.to_thread(read_excel, filepath)
    if not rows: return

    # Initialize per-file progress tracker
    progress = FileProgressTracker(filepath)

    # Disk cleanup integration
    from utils.disk_cleanup import check_and_cleanup
    check_and_cleanup()

    tracker = PerformanceTracker()
    tracker.start_file_processing()
    await asyncio.to_thread(sync_with_previous_results, rows, filepath, progress)
    
    rows_to_process = [r for r in rows if r.status != "DONE"] if config.REPROCESS_FAILED_ROWS else [r for r in rows if r.status not in ("DONE", "NO TEL", "SKIP")]
    total = len(rows_to_process)
    
    if total == 0:
        logger.info(f"[Agent] ⏭️  Skipping '{os.path.basename(filepath)}' — 0 rows to process.")
    else:
        logger.info(f"[Agent] 🔄 Processing {total} rows from '{os.path.basename(filepath)}'...")
        save_lock, sem = asyncio.Lock(), asyncio.Semaphore(config.MAX_CONCURRENT_WORKERS)
        tasks = [asyncio.create_task(_worker_process_row(r, sem, save_lock, rows, filepath, tracker, i, total, progress)) for i, r in enumerate(rows_to_process, 1)]
        await asyncio.gather(*tasks)
    
    await asyncio.to_thread(save_results, rows, filepath)
    tracker.end_file_processing()
    await finalize_file_processing(rows, filepath, tracker, progress)

async def finalize_file_processing(
    rows: List[ExcelRow], original_filepath: str, tracker: Optional[PerformanceTracker] = None, progress: FileProgressTracker = None
) -> None:
    orig_path = Path(original_filepath)
    success_rows = [r for r in rows if r.phone or r.status == "DONE"]
    retry_rows = [r for r in rows if r.status in ("NO TEL", "SKIP", "PENDING", "ERROR")]

    total = len(rows)
    duration_str = f"{tracker.get_metrics_summary()['total_execution_seconds']}s" if tracker else "N/A"

    logger.info("")
    logger.info(f"{'━' * 60}")
    logger.info(f"📊  FILE COMPLETED: {orig_path.name}")
    logger.info(f"   📁 Total: {total} | ⏱️ Duration: {duration_str}")
    logger.info(f"   ✅ Success: {len(success_rows)} | 🔁 Retry: {len(retry_rows)}")
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
        progress.delete()
    try: os.remove(original_filepath)
    except: pass
