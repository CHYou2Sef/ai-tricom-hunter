"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/logger.py                                                         ║
║                                                                          ║
║  Centralised logging setup.                                              ║
║  All modules call get_logger(__name__) to get a logger that:             ║
║    ✓ Prints to the console with colors                                   ║
║    ✓ Saves to a daily rotating log file in /logs/                        ║
║                                                                          ║
║  BEGINNER NOTE:                                                          ║
║    Python's built-in `logging` module is the standard way to track      ║
║    what a program is doing.  Never use print() in production code —     ║
║    use logging instead because you can control verbosity levels and      ║
║    automatically save to files.                                          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
import os
import contextlib
from logging.handlers import TimedRotatingFileHandler, RotatingFileHandler

from core import config
import gzip
import shutil

# Ensure the log directory exists
from common.fs import safe_mkdir as _safe_mkdir
_safe_mkdir(config.LOG_DIR)


@contextlib.contextmanager
def verbose_logging(level: int = logging.DEBUG):
    """
    Context manager to temporarily enable verbose logging.
    Useful for debugging issues in a specific block of code.

    Example:
        with verbose_logging():
            do_complex_task()
    """
    root = logging.getLogger()
    old_level = root.level
    root.setLevel(level)
    try:
        yield
    finally:
        root.setLevel(old_level)


# ─────────────────────────────────────────────────────────────────────────────
# COLOR FORMATTER (for console output only)
# ─────────────────────────────────────────────────────────────────────────────

# ── Custom Log Levels ──
TRACE = 5
FATAL = 60
logging.addLevelName(TRACE, "TRACE")
logging.addLevelName(FATAL, "FATAL")

COLORS = {
    "TRACE":    "\033[90m",   # Gray
    "DEBUG":    "\033[94m",   # Blue
    "INFO":     "\033[92m",   # Green
    "WARNING":  "\033[93m",   # Yellow
    "ERROR":    "\033[91m",   # Red
    "CRITICAL": "\033[95m",   # Magenta
    "FATAL":    "\033[41m\033[97m", # White on Red background
    "RESET":    "\033[0m",    # Reset to default
}

LOG_FORMAT    = "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s"
DATE_FORMAT   = "%Y-%m-%d %H:%M:%S"


class ColorFormatter(logging.Formatter):
    """Custom formatter that adds colors to console log messages."""

    def format(self, record: logging.LogRecord) -> str:
        color = COLORS.get(record.levelname, COLORS["RESET"])
        reset = COLORS["RESET"]
        # Use a copy of levelname to avoid modifying it globally
        original_levelname = record.levelname
        record.levelname = f"{color}{original_levelname}{reset}"
        formatted = super().format(record)
        record.levelname = original_levelname
        return formatted


# ─────────────────────────────────────────────────────────────────────────────
# LOG ROTATION HELPERS (Compression)
# ─────────────────────────────────────────────────────────────────────────────

def _log_namer(name: str) -> str:
    """Append .gz to the rotated log file name."""
    return name + ".gz"

def _log_rotator(source: str, dest: str) -> None:
    """Compress the log file using gzip after rotation."""
    with open(source, "rb") as f_in:
        with gzip.open(dest, "wb") as f_out:
            shutil.copyfileobj(f_in, f_out)
    os.remove(source)


# ─────────────────────────────────────────────────────────────────────────────
# SINGLETON PATTERN
# ─────────────────────────────────────────────────────────────────────────────

_configured = False


def _setup_root_logger() -> None:
    """
    Configure the root logger with:
      1. A console handler (INFO+ by default)
      2. A file handler for CRITICAL ERRORS (no archive, simple overwrite)
      3. A rotating file handler for COMPLETE HISTORY (all levels, rotated)
    """
    global _configured
    if _configured:
        return

    root = logging.getLogger()
    # Capture everything internally, handlers will filter
    root.setLevel(logging.DEBUG)

    # ── Anti-Root Permission Guard (Execute BEFORE opening handlers) ──
    error_file = os.path.join(config.LOG_DIR, "agent.log")
    archive_file = os.path.join(config.LOG_DIR, "debug_archive.log")
    
    for f in [config.LOG_DIR, error_file, archive_file]:
        if os.path.exists(f):
            try: os.chmod(f, 0o755)
            except: pass

    # ── 1. Console handler ──
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(
        ColorFormatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    )

    # ── 2. "Clean" error log file (Only ERRORS and CRITICAL) ──
    # This prevents disk fill-up with trivial infologs
    error_handler = RotatingFileHandler(
        error_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=5,              # Keep 5 error archives
        encoding="utf-8"
    )
    error_handler.namer   = _log_namer
    error_handler.rotator = _log_rotator
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(
        logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    )

    # ── 3. High-Res Rotation log (Persistent history for monitoring) ──
    # Rotates at 10MB, keeps latest 5 files.
    archive_file = os.path.join(config.LOG_DIR, "debug_archive.log")
    archive_handler = RotatingFileHandler(
        archive_file,
        maxBytes=10 * 1024 * 1024,  # 10 MB
        backupCount=10,             # Keep more archives since they are compressed
        encoding="utf-8"
    )
    archive_handler.namer   = _log_namer
    archive_handler.rotator = _log_rotator
    archive_handler.setLevel(logging.INFO)     # Preserve full execution history (rotated & compressed)
    archive_handler.setFormatter(
        logging.Formatter(fmt=LOG_FORMAT, datefmt=DATE_FORMAT)
    )

    # ── 4. Silence noisy third-party libraries ──
    logging.getLogger("nodriver").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)
    logging.getLogger("playwright").setLevel(logging.WARNING)
    logging.getLogger("watchdog").setLevel(logging.WARNING)

    root.addHandler(console_handler)
    root.addHandler(error_handler)
    root.addHandler(archive_handler)

    _configured = True


def get_logger(name: str) -> logging.Logger:
    """
    Get a named logger with support for TRACE and FATAL levels.
    """
    _setup_root_logger()
    logger = logging.getLogger(name)
    
    # Add helper methods for custom levels if they don't exist
    if not hasattr(logger, 'trace'):
        logger.trace = lambda msg, *args, **kwargs: logger.log(TRACE, msg, *args, **kwargs)
    if not hasattr(logger, 'fatal'):
        logger.fatal = lambda msg, *args, **kwargs: logger.log(FATAL, msg, *args, **kwargs)
        
    return logger


# ─────────────────────────────────────────────────────────────────────────────
# TASK 6: THREE-TIER ALERT SYSTEM  (GEMINI.md § Task 6)
#
# Alert levels and their triggers:
#
#  INFO     → Proxy rotated, session started, row done, CAPTCHA solved
#             Action: log to file only (no console noise)
#
#  WARN     → 403/429 response received, CAPTCHA detected, proxy slow,
#             stale connection detected (first occurrence)
#             Action: log + yellow banner on console
#
#  CRITICAL → Proxy BAN streak ≥ 3, CAPTCHA unsolvable after timeout,
#             stale connection loop (≥ MAX_RECONNECT_ATTEMPTS failures),
#             all proxy tiers exhausted
#             Action: log + red block banner on console
# ─────────────────────────────────────────────────────────────────────────────

_alert_logger = None


def _get_alert_logger() -> logging.Logger:
    """Lazy-init a dedicated logger for structured alerts."""
    global _alert_logger
    if _alert_logger is None:
        _setup_root_logger()
        _alert_logger = logging.getLogger("ALERT")
    return _alert_logger


# Console banner templates
_WARN_BORDER     = "⚠️  " + "─" * 56
_CRITICAL_BORDER = "🚨  " + "═" * 56


def alert(level: str, message: str, context: dict = None) -> None:
    """
    Fire a structured alert at the given level.

    Args:
        level   : "INFO" | "WARN" | "CRITICAL"
        message : Human-readable alert message
        context : Optional dict with extra fields (proxy, url, status_code, …)

    Trigger table (GEMINI.md Task 6):
    ┌──────────┬──────────────────────────────────────────────────────┐
    │  INFO    │ Proxy rotated successfully                           │
    │          │ New browser session started                          │
    │          │ Row processing completed (DONE)                      │
    │          │ CAPTCHA manually solved                              │
    ├──────────┼──────────────────────────────────────────────────────┤
    │  WARN    │ HTTP 403 or 429 received                             │
    │          │ CAPTCHA page detected                                │
    │          │ Proxy errors ≥ PROXY_WARN_THRESHOLD                  │
    │          │ Stale connection detected (first attempt)            │
    │          │ Session duration < 60s (suspicious short session)    │
    ├──────────┼──────────────────────────────────────────────────────┤
    │ CRITICAL │ Proxy BAN streak ≥ 3 consecutive rotations          │
    │          │ CAPTCHA unsolvable (manual timeout reached)          │
    │          │ Stale connection loop: ≥ MAX_RECONNECT_ATTEMPTS      │
    │          │ All proxy pool sources exhausted                     │
    │          │ Browser process crashed and could not restart        │
    └──────────┴──────────────────────────────────────────────────────┘
    """
    alogger = _get_alert_logger()
    ctx_str  = f" | ctx={context}" if context else ""
    full_msg = f"{message}{ctx_str}"

    level_upper = level.upper()

    if level_upper == "INFO":
        alogger.info(f"[ALERT/INFO] {full_msg}")

    elif level_upper == "WARN":
        alogger.warning(f"[ALERT/WARN] {full_msg}")
        # Console banner
        print(f"\n{_WARN_BORDER}")
        print(f"⚠️   WARN  |  {message}")
        if context:
            for k, v in context.items():
                print(f"   {k}: {v}")
        print(f"{_WARN_BORDER}\n")

    elif level_upper == "CRITICAL":
        alogger.critical(f"[ALERT/CRITICAL] {full_msg}")
        # Prominent console block
        print(f"\n{_CRITICAL_BORDER}")
        print(f"🚨  CRITICAL  |  {message}")
        if context:
            for k, v in context.items():
                print(f"   {k}: {v}")
        print(f"{_CRITICAL_BORDER}\n")

    else:
        alogger.info(f"[ALERT/{level_upper}] {full_msg}")


def stale_connection_alert(attempt: int, max_attempts: int, detail: str = "") -> None:
    """
    Convenience wrapper for stale-connection events.

    - First occurrence (attempt < max_attempts) → WARN
    - All retries exhausted (attempt >= max_attempts) → CRITICAL

    Args:
        attempt     : Current reconnect attempt number (1-indexed)
        max_attempts: Maximum allowed reconnects (config.BROWSER_MAX_RECONNECT_ATTEMPTS)
        detail      : Optional error message from the exception
    """
    context = {"attempt": f"{attempt}/{max_attempts}", "detail": detail or "N/A"}
    if attempt >= max_attempts:
        alert(
            "CRITICAL",
            f"Stale browser connection — all {max_attempts} reconnect attempts failed",
            context,
        )
    else:
        alert(
            "WARN",
            f"Stale browser connection detected — reconnecting (attempt {attempt})",
            context,
        )
