"""
╔══════════════════════════════════════════════════════════════════════════╗
║  run/supervisor.py  —  3-Layer Autonomous Supervisor                     ║
║                                                                          ║
║  Starts all three layers in a single process:                            ║
║    Layer 0  → Ingest LangGraph (watchdog + classify + route)             ║
║    Layer 1  → Phone Hunter waterfall (existing orchestrator)             ║
║    Layer 2  → Social URL fallback (auto-activated from phone_hunter)     ║
║    Monitor  → FastAPI Monitoring API (:8000)                             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import sys
import os
import gc
from pathlib import Path

# ── CRITICAL: Set up sys.path BEFORE any heavy imports (uvicorn/numpy/pandas) ──
# Use append() NOT insert(0,...) so site-packages always have priority over the
# project root. insert(0,...) causes numpy "do not import from source directory"
# errors in containerized environments where /app or /app/src shadows site-pkgs.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.append(str(PROJECT_ROOT))
if str(PROJECT_ROOT / "src") not in sys.path:
    sys.path.append(str(PROJECT_ROOT / "src"))

# Also clean any PYTHONPATH-injected paths that might shadow site-packages.
# In Docker, PYTHONPATH=/app/src can end up at position 0 via the environment,
# but site-packages must stay FIRST for binary C-extensions (numpy, pandas).
_SITE_PKGS = [p for p in sys.path if "site-packages" in p]
_OTHERS    = [p for p in sys.path if "site-packages" not in p]
sys.path[:] = _SITE_PKGS + _OTHERS

# pyrefly: ignore [missing-import]
import bootstrap  # noqa: F401 — websockets shim + logging init

import asyncio
import time
import socket
import uvicorn  # noqa — imported AFTER bootstrap path sanitization

from core import config
from core.logger import get_logger
from core.singleton import ensure_singleton
from app.orchestrator import (
    process_file_async,
    init_agent_pool,
    close_agent_pool,
    FILE_PROCESSING_TIMEOUT_SEC,
)
from agents.layer0 import process_incoming_file, set_l1_queue
from app.monitoring.app import app as monitoring_app

try:
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler
except ImportError:
    raise SystemExit("❌ Missing dependency: pip install watchdog")

logger = get_logger("supervisor")

# ── Memory watchdog thresholds ──────────────────────────────────────────────────
# WARNING: this triggers a graceful self-restart via os.execv.
# Must stay ABOVE the orchestrator's RAM_HIGHWATER_PCT (82%) so the
# orchestrator has a chance to back-pressure before the supervisor restarts.
SUPERVISOR_RAM_RESTART_PCT: float = float(os.getenv("SUPERVISOR_RAM_RESTART_PCT", "90"))
SUPERVISOR_WATCHDOG_INTERVAL_SEC: int = int(os.getenv("SUPERVISOR_WATCHDOG_INTERVAL_SEC", "60"))


def check_internet(host: str = "www.google.com", port: int = 443, timeout: int = 5) -> bool:
    """Check basic internet connectivity with a fallback to a second host."""
    try:
        # Try primary host
        socket.setdefaulttimeout(timeout)
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.connect((host, port))
        return True
    except Exception:
        try:
            # Fallback to secondary host (Cloudflare)
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect(("1.1.1.1", 53))
            return True
        except Exception:
            return False


class IngestHandler(FileSystemEventHandler):
    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self.loop = loop

    def on_created(self, event) -> None:
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event) -> None:
        if not event.is_directory:
            self._handle(event.dest_path)

    def _handle(self, path: str) -> None:
        p = Path(path)
        if p.name.startswith((".", "~")): return
        if p.suffix.lower() not in config.ACCEPTED_EXTENSIONS: return
        if p.name.endswith(".meta.json"): return

        time.sleep(config.FILE_SETTLE_DELAY)
        if not p.exists(): return

        logger.info(f"[Supervisor|L0] 📂 File detected: {p.name}")
        state = process_incoming_file(str(p))
        logger.info(
            f"[Supervisor|L0] {p.name} → {state.get('final_status')} "
            f"({len(state.get('emitted_events', []))} file(s) emitted to L1)"
        )


async def _memory_watchdog() -> None:
    """
    Background task that monitors system RAM and CPU every
    SUPERVISOR_WATCHDOG_INTERVAL_SEC seconds.

    If RAM ≥ SUPERVISOR_RAM_RESTART_PCT the supervisor performs a graceful
    self-restart via os.execv so the container orchestrator can respawn it
    from the last checkpoint.  This is the final safety net — the orchestrator
    already back-pressures at 82%; we should rarely reach 90%.
    """
    while True:
        await asyncio.sleep(SUPERVISOR_WATCHDOG_INTERVAL_SEC)
        try:
            import psutil
            mem = psutil.virtual_memory()
            cpu = psutil.cpu_percent(interval=1)
            ram_pct = mem.percent
            logger.info(
                f"[Supervisor|Watchdog] 📊 RAM={ram_pct:.1f}% "
                f"({mem.used // 1024 // 1024} MB / {mem.total // 1024 // 1024} MB) "
                f"CPU={cpu:.1f}%"
            )
            if ram_pct >= SUPERVISOR_RAM_RESTART_PCT:
                logger.critical(
                    f"[Supervisor|Watchdog] 🚨 RAM CRITICAL at {ram_pct:.1f}% "
                    f"(≥{SUPERVISOR_RAM_RESTART_PCT}%) — initiating graceful restart "
                    "so container can respawn from last checkpoint..."
                )
                # Give in-flight rows 15s to flush their checkpoints before restart.
                await asyncio.sleep(15)
                os.execv(sys.executable, [sys.executable] + sys.argv)
        except ImportError:
            # psutil not installed — watchdog still runs but without metrics
            await asyncio.sleep(SUPERVISOR_WATCHDOG_INTERVAL_SEC)
        except Exception as exc:
            logger.warning(f"[Supervisor|Watchdog] Watchdog error (ignored): {exc}")


async def layer1_consumer(file_queue: asyncio.Queue) -> None:
    while True:
        if not check_internet():
            logger.warning("[Supervisor|L1] ⚠️  Internet lost. Pausing...")
            while not check_internet(): await asyncio.sleep(5)
            logger.info("[Supervisor|L1] 🌐 Internet restored.")

        filepath = await file_queue.get()
        if not os.path.exists(filepath):
            file_queue.task_done()
            continue

        try:
            logger.info(
                f"[Supervisor|L1] 📦 Processing '{Path(filepath).name}' "
                f"(timeout={FILE_PROCESSING_TIMEOUT_SEC:.0f}s)..."
            )
            await asyncio.wait_for(
                process_file_async(filepath),
                timeout=FILE_PROCESSING_TIMEOUT_SEC,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[Supervisor|L1] ⏰ File '{Path(filepath).name}' exceeded "
                f"{FILE_PROCESSING_TIMEOUT_SEC:.0f}s timeout — "
                "forcing checkpoint flush and moving to next file."
            )
        except Exception as exc:
            logger.error(
                f"[Supervisor|L1] ❌ Error on '{Path(filepath).name}': {exc}",
                exc_info=True,
            )
        finally:
            # Explicit GC pass after each file: forces Python to return
            # Chromium/Playwright heap segments back to the OS between batches.
            gc.collect()

        file_queue.task_done()
        if file_queue.empty():
            from common.metrics import get_layer_telemetry
            logger.info("[Supervisor|L1] 💤 Queue empty — waiting for Layer 0...")
            print(get_layer_telemetry().get_report())


def scan_existing_files(file_queue: asyncio.Queue, seen: set) -> int:
    buckets = [config.INPUT_STD_DIR, config.INPUT_RS_DIR, config.INPUT_SIR_DIR, config.INPUT_OTHER_DIR, config.READY_DIR]
    count = 0
    for bucket in buckets:
        if not Path(bucket).exists(): continue
        for fname in sorted(os.listdir(bucket)):
            ext = os.path.splitext(fname)[1].lower()
            if ext not in config.ACCEPTED_EXTENSIONS or fname.endswith(".meta.json"): continue
            fpath = os.path.join(bucket, fname)
            if fpath not in seen:
                file_queue.put_nowait(fpath)
                seen.add(fpath)
                count += 1
    return count


async def main() -> None:
    _lock = ensure_singleton("supervisor", config.WORK_DIR)
    file_queue: asyncio.Queue = asyncio.Queue()
    set_l1_queue(file_queue)

    if not check_internet():
        logger.warning("[Supervisor] ⚠️  Internet check failed. Continuing anyway, but scraping may fail.")
    else:
        logger.info("[Supervisor] 🌐 Internet connectivity confirmed.")

    # 1. Start Monitoring API in background
    config_uvicorn = uvicorn.Config(
        monitoring_app, host="0.0.0.0", port=8000, 
        log_level="warning", access_log=False
    )
    server = uvicorn.Server(config_uvicorn)
    api_task = asyncio.create_task(server.serve())
    logger.info("[Supervisor] 🛰️  Monitoring API started on port 8000")

    # 2. Init browser pool for Layer 1
    await init_agent_pool(config.MAX_CONCURRENT_WORKERS)

    # 2b. Start memory watchdog in background
    watchdog_task = asyncio.create_task(_memory_watchdog())
    logger.info(
        f"[Supervisor] 👁️  Memory watchdog started "
        f"(interval={SUPERVISOR_WATCHDOG_INTERVAL_SEC}s, "
        f"restart_at={SUPERVISOR_RAM_RESTART_PCT}%)"
    )

    # 3. Process orphaned files in INCOMING_DIR
    from common.fs import safe_mkdir
    safe_mkdir(config.INCOMING_DIR)
    
    files_in_incoming = sorted(os.listdir(config.INCOMING_DIR))
    logger.info(f"[Supervisor] Found {len(files_in_incoming)} total items in INCOMING.")
    
    orphaned_count = 0
    for fname in files_in_incoming:
        if fname.startswith((".", "~")) or fname.endswith(".meta.json"): 
            logger.debug(f"[Supervisor] Ignoring system/meta file: {fname}")
            continue
            
        p = Path(config.INCOMING_DIR) / fname
        if p.is_file():
            if p.suffix.lower() in config.ACCEPTED_EXTENSIONS:
                logger.info(f"[Supervisor|L0] 📂 Orphaned file detected at startup: {p.name}")
                process_incoming_file(str(p))
                orphaned_count += 1
            else:
                logger.warning(f"[Supervisor|L0] ⚠️ File {fname} has unsupported extension {p.suffix}. Accepted: {config.ACCEPTED_EXTENSIONS}")
        else:
            logger.debug(f"[Supervisor] Ignoring non-file item: {fname}")

    if orphaned_count:
        logger.info(f"[Supervisor] Processed {orphaned_count} orphaned file(s) from INCOMING.")
    else:
        logger.info("[Supervisor] No valid files found in INCOMING at startup.")

    # 4. Pre-load existing classified files
    seen: set = set()
    pre_loaded = scan_existing_files(file_queue, seen)
    if pre_loaded:
        logger.info(f"[Supervisor] {pre_loaded} existing file(s) queued for Layer 1.")

    # 4. Start watchdog for Layer 0
    loop     = asyncio.get_running_loop()
    handler  = IngestHandler(loop=loop)
    observer = Observer()
    observer.schedule(handler, path=str(config.INCOMING_DIR), recursive=False)
    observer.start()

    from common.fs import safe_mkdir
    safe_mkdir(config.INCOMING_DIR)

    layer2_status = "ON ✅" if getattr(config, "LAYER2_ENABLED", True) else "OFF ⛔"

    print("\n" + "═" * 62)
    print("  🤖  AI Tricom Hunter — Autonomous 3-Layer Supervisor")
    print(f"  📥  Layer 0 watching : {config.INCOMING_DIR}")
    print(f"  🔍  Layer 1 workers  : {config.MAX_CONCURRENT_WORKERS}")
    print(f"  🔗  Layer 2 fallback : {layer2_status}")
    print(f"  📂  Output root      : {config.OUTPUT_ROOT}")
    print("  Press Ctrl+C to stop.")
    print("═" * 62 + "\n")

    try:
        await layer1_consumer(file_queue)
    except asyncio.CancelledError:
        logger.info("[Supervisor] 🛑 Shutdown signal received.")
    finally:
        # Cancel memory watchdog
        watchdog_task.cancel()
        try:
            await watchdog_task
        except asyncio.CancelledError:
            pass

        observer.stop()
        observer.join()
        # Uvicorn shutdown can crash if dependency versions mismatch (uvicorn/websockets).
        # Avoid killing the whole supervisor with an exception during SIGINT.
        try:
            await server.shutdown()
        except Exception as exc:
            logger.warning(f"[Supervisor] Monitoring API shutdown error (ignored): {exc}")
        await close_agent_pool()

        print("\n" + "━" * 62)
        print("🏁  Supervisor stopped. All layers shut down.")
        print("━" * 62 + "\n")


def main_sync() -> None:
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n[Supervisor] Stopped by user.\n")


if __name__ == "__main__":
    main_sync()
