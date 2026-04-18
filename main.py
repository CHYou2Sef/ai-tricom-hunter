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

logger = get_logger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# DIRECTORY SETUP
# ─────────────────────────────────────────────────────────────────────────────

def ensure_directories() -> None:
    """Create only essential directories at startup with world-writable permissions."""
    from utils.fs import safe_mkdir
    dirs = [
        config.WORK_DIR,
        config.INCOMING_DIR,
        config.LOG_DIR,
    ]
    for d in dirs:
        safe_mkdir(d)
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

    print(f"\n{'━' * 60}")
    print(f"📡 Agent is LIVE. Browsing mode active.")
    print(f"   Workers: {config.MAX_CONCURRENT_WORKERS} | Save interval: every {config.SAVE_INTERVAL} rows")
    print(f"   Watching: {', '.join(os.path.basename(str(d)) for d in watch_dirs if os.path.exists(d))}")
    print(f"   Press Ctrl+C to stop.")
    print(f"{'━' * 60}\n")

    try:
        while True:
            filepath = await file_queue.get()
            
            if not os.path.exists(filepath):
                logger.warning(f"[Main] ⚠️  File vanished before processing: {os.path.basename(filepath)}")
                file_queue.task_done()
                continue
            
            try:
                # ── Search & Enrich Phase ──
                # At this point, the file is already classfied (and decomposed if needed) by pre_process.py
                await process_file_async(filepath)
            except PermissionError as e:
                logger.error(
                    f"[Main] 🔒 PERMISSION DENIED on '{os.path.basename(filepath)}': {e}\n"
                    f"       → Fix: run 'sudo chown -R $USER:$USER WORK/' on host"
                )
            except Exception as e:
                logger.error(f"[Main] ❌ Error processing '{os.path.basename(filepath)}': {e}", exc_info=True)
            
            file_queue.task_done()

            # Show idle status when queue is empty
            if file_queue.empty():
                logger.info("[Main] 💤 Queue empty. Waiting for new files...")
            
    except asyncio.CancelledError:
        logger.info("[Main] 🛑 Shutdown signal received.")
    except Exception as e:
        logger.error(f"[Main] 💥 Unexpected loop error: {e}", exc_info=True)
    finally:
        observer.stop()
        observer.join()
        await close_agent_pool()

        print(f"\n{'━' * 60}")
        print(f"🏁  SESSION TERMINÉE")
        print(f"{'─' * 60}")
        print(f"   🌐 Browser pool closed.")
        print(f"   🧹 Cleanup finished.")
        print(f"   📂 Results in: {config.OUTPUT_ROOT}")
        print(f"{'━' * 60}\n")
        
        cleanup_input_folders()


def main():
    try:
        asyncio.run(main_async())
    except KeyboardInterrupt:
        print(f"\n\n{'━' * 60}")
        print(f"⏹️   Agent arrêté par l'utilisateur.")
        print(f"{'━' * 60}\n")

if __name__ == "__main__":
    main()
