"""
╔══════════════════════════════════════════════════════════════════════════╗
║  main.py  —  Entry Point & 24/7 Watchdog (ASYNC VERSION)                 ║
║                                                                          ║
║  Run this file to start the agent:                                       ║
║      python main.py                                                      ║
║                                                                          ║
║  The agent will:                                                         ║
║    1. Watch the /input/ folder continuously for new Excel files          ║
║    2. Process each file automatically as soon as it appears              ║
║    3. Save results to /output/RS_Adr/ or /output/Siret_Siren_Adr/       ║
║    4. Keep running 24/7 until you press Ctrl+C                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import asyncio
from pathlib import Path

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler, FileCreatedEvent
    WATCHDOG_AVAILABLE = True
except ImportError:
    # ── Watchdog Fallback (Simple Polling) ──
    WATCHDOG_AVAILABLE = False
    class FileSystemEventHandler: pass
    class FileCreatedEvent: pass
    class Observer:
        def __init__(self, *args, **kwargs): self.scheduled = []
        def schedule(self, handler, path, recursive=False): self.scheduled.append((handler, path))
        def start(self): pass
        def stop(self): pass
        def join(self): pass

import config
from agent import process_file_async, init_agent_pool, close_agent_pool
from utils.logger import get_logger
from utils.health_check import check_all
from utils.lock_manager import acquire_lock, release_lock

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORY SETUP
# ─────────────────────────────────────────────────────────────────────────────

def ensure_directories() -> None:
    """Create all required directories if they don't already exist."""
    dirs = [
        config.WORK_DIR,
        config.INCOMING_DIR,
        config.INPUT_STD_DIR,
        config.INPUT_SIR_DIR,
        config.INPUT_RS_DIR,
        config.INPUT_OTHER_DIR,
        config.READY_DIR,
        config.OUTPUT_ROOT,
        config.OUTPUT_RS_ADR,
        config.OUTPUT_SIR_ADR,
        config.OUTPUT_DEFAULT,
        config.ARCHIVE_BACKUP_DIR,
        config.OUTPUT_SUCCEED_DIR,
        config.OUTPUT_FAILED_DIR,
        config.LOG_DIR,
    ]
    for d in dirs:
        os.makedirs(d, exist_ok=True)
        logger.debug(f"[Setup] Verified directory: {d}")

def cleanup_input_folders() -> None:
    """Safely cleans up temporary processing folders in input/."""
    import shutil
    # List of folder basenames we must NEVER delete
    keep_dirs = [
        "INCOMING", "STD", "SIREN", "RS", "OTHERS", "READY", "output", "ARCHIVE"
    ]
    
    input_root = config.INPUT_DIR
    if not os.path.exists(input_root):
        return

    for d in os.listdir(input_root):
        dir_path = os.path.join(input_root, d)
        if os.path.isdir(dir_path) and d not in keep_dirs:
            try:
                # Only delete if it's not a hidden system folder
                if not d.startswith("."):
                    shutil.rmtree(dir_path)
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# WATCHDOG FILE HANDLER
# ─────────────────────────────────────────────────────────────────────────────

class ExcelFileHandler(FileSystemEventHandler):
    def __init__(self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop):
        super().__init__()
        self.queue = queue
        self.loop = loop
        self._seen = set()

    def on_created(self, event: FileCreatedEvent) -> None:
        if event.is_directory: return
        filepath = event.src_path
        if filepath.endswith(".meta.json"): return # Skip
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in config.ACCEPTED_EXTENSIONS: return
        if filepath in self._seen: return
        self._seen.add(filepath)

        logger.info(f"[Watchdog] 📂 New file detected: {os.path.basename(filepath)}")
        # Settle delay to ensure file is written completely by OS
        time.sleep(config.FILE_SETTLE_DELAY)
        
        self.loop.call_soon_threadsafe(self.queue.put_nowait, filepath)

    def on_modified(self, event) -> None:
        if event.is_directory: return
        filepath = event.src_path
        if filepath.endswith(".meta.json"): return # Skip
        ext = os.path.splitext(filepath)[1].lower()
        if ext not in config.ACCEPTED_EXTENSIONS: return

        if filepath not in self._seen:
            self._seen.add(filepath)
            logger.info(f"[Watchdog] 📝 Modified file detected: {os.path.basename(filepath)}")
            time.sleep(config.FILE_SETTLE_DELAY)
            self.loop.call_soon_threadsafe(self.queue.put_nowait, filepath)

def scan_existing_files(queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, seen_files: set = None) -> int:
    """Pre-load existing files from all processing buckets into the queue."""
    if seen_files is None: seen_files = set()
    priority_dirs = [
        config.INPUT_STD_DIR,
        config.INPUT_RS_DIR,
        config.INPUT_SIR_DIR,
        config.INPUT_OTHER_DIR,
        config.READY_DIR
    ]
    count = 0
    for d in priority_dirs:
        if not os.path.exists(d): continue
        for filename in sorted(os.listdir(d)):
            ext = os.path.splitext(filename)[1].lower()
            if ext in config.ACCEPTED_EXTENSIONS:
                if filename.endswith(".meta.json"): continue # Skip meta
                filepath = os.path.join(d, filename)
                if filepath not in seen_files:
                    logger.info(f"[Setup] Prioritizing {filename} from {os.path.basename(d)}")
                    loop.call_soon_threadsafe(queue.put_nowait, filepath)
                    seen_files.add(filepath)
                    count += 1
    return count


# ─────────────────────────────────────────────────────────────────────────────
# MAIN LOOP
# ─────────────────────────────────────────────────────────────────────────────

async def main_async() -> None:
    """Asynchronous entry point for the AI agent."""
    print("\n" + "═" * 60)
    print("  🤖  AI Tricom Hunter Agent (V4 INDUSTRIAL)")
    print(f"  📂  Queue Source:  {config.WORK_DIR.name}/ (Watching buckets: STD, RS, SIREN, READY)")
    print(f"  🔍  Engine:        HYBRID WATERFALL (Tier {config.HYBRID_DEFAULT_TIER} Default)")
    print("═" * 60 + "\n")

    ensure_directories()
    
    # ── SINGLETON LOCK (Conflict Prevention) ──
    instance_name = "DOCKER-AGENT" if getattr(config, "DOCKER_ENV", False) else f"LOCAL-{os.getlogin()}"
    if not acquire_lock(instance_name):
        logger.critical(f"🛑 SHUTDOWN: Conflict detected. Another agent is already using the {config.WORK_DIR} directory.")
        print(f"\n🚨  CONFLICT ALERT: Only ONE agent can manage the WORK directory at a time.")
        print(f"    Please stop the other instance before starting this one.\n")
        return

    # Initialize the agent pool for true parallelism
    await init_agent_pool(config.MAX_CONCURRENT_WORKERS)

    loop = asyncio.get_running_loop()
    file_queue = asyncio.Queue()
    global_seen = set()

    scan_existing_files(file_queue, loop, seen_files=global_seen)

    handler = ExcelFileHandler(queue=file_queue, loop=loop)
    # Give handler access to global_seen so watchdog doesn't re-add files already in queue
    handler._seen = global_seen
    observer = Observer()

    watch_dirs = [
        config.INPUT_STD_DIR,
        config.INPUT_RS_DIR,
        config.INPUT_SIR_DIR,
        config.INPUT_OTHER_DIR,
        config.READY_DIR
    ]
    
    for d in watch_dirs:
        if os.path.exists(d):
            observer.schedule(handler, path=d, recursive=False)

    if WATCHDOG_AVAILABLE:
        observer.start()
    else:
        logger.warning("[Setup] watchdog not installed. Falling back to simple polling.")
        # Start a simple periodic scan task
        async def poll_files():
            while True:
                scan_existing_files(file_queue, loop, seen_files=global_seen)
                await asyncio.sleep(config.WATCHDOG_POLL_INTERVAL * 2)
        asyncio.create_task(poll_files())

    print(f"\n📡 Agent is LIVE. Browsing mode active.")
    print("   Press Ctrl+C to stop.\n")

    try:
        while True:
            filepath = await file_queue.get()
            
            if not os.path.exists(filepath):
                logger.warning(f"[Main] File no longer exists: {filepath}")
                file_queue.task_done()
                continue
            
            try:
                # ── Search & Enrich Phase ──
                # At this point, the file is already classfied (and decomposed if needed) by pre_process.py
                await process_file_async(filepath)
            except Exception as e:
                logger.error(f"[Main] Error processing {os.path.basename(filepath)}: {e}", exc_info=True)
            
            file_queue.task_done()
            
    except asyncio.CancelledError:
        logger.info("[Main] Shutdown signalled.")
    except Exception as e:
        logger.error(f"[Main] Unexpected loop error: {e}", exc_info=True)
    finally:
        observer.stop()
        observer.join()
        await close_agent_pool()
        logger.info("[Main] Browser pool closed.")
        
        release_lock()
        
        cleanup_input_folders()
        logger.info("[Main] Cleanup finished. Goodbye!")


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print("\n\n⏹️  Agent stopped by user.\n")

if __name__ == "__main__":
    main()
