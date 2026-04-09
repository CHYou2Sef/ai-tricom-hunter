"""
utils/disk_cleanup.py

Proactive disk space management (Bug #5 fix from rapport_technique_webdrivers).

Why this exists:
    The AI Tricom Hunter launches many browser sessions in sequence.
    Each session creates temporary Chrome profiles in /tmp/ and accumulates
    Playwright/Crawl4AI cache in ~/.cache/ms-playwright and ~/.crawl4ai_cache.
    When these fill the disk quota, ALL Python processes fail to write anything
    (even log rotation), freezing the entire agent.

Integration:
    Called automatically at the top of HybridEngine._execute_with_waterfall()
    before every extraction attempt. It is a "best-effort" check (never raises).

Usage (standalone):
    from utils.disk_cleanup import check_and_cleanup
    check_and_cleanup(threshold_pct=85)
"""

import glob
import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)


def _get_disk_usage_pct(path: str = "/") -> float:
    """Return the percentage of disk space used on the partition containing `path`."""
    try:
        usage = shutil.disk_usage(path)
        return usage.used / usage.total * 100
    except Exception:
        return 0.0


def _safe_remove(path: Path) -> int:
    """
    Remove a file or directory tree safely.
    Returns the number of bytes freed (best-effort approximation).
    """
    freed = 0
    try:
        if path.is_dir():
            freed = sum(
                f.stat().st_size
                for f in path.rglob("*")
                if f.is_file()
            )
            shutil.rmtree(path, ignore_errors=True)
        elif path.is_file():
            freed = path.stat().st_size
            path.unlink(missing_ok=True)
    except Exception as exc:
        logger.debug(f"[DiskCleanup] Could not remove {path}: {exc}")
    return freed


def cleanup_browser_caches() -> int:
    """
    Remove ephemeral browser caches created by Playwright and Crawl4AI.

    Targets (all safe to delete — session data only, no user profiles):
      - /tmp/patchright_chromium*   ← Patchright temp profiles
      - /tmp/playwright_chromium*   ← Playwright temp profiles (legacy/fallback)
      - /tmp/uc_*                   ← Nodriver (UC) temp profiles
      - ~/.crawl4ai_cache/          ← Crawl4AI page cache
      - /tmp/crawl4ai_*             ← Crawl4AI temp data
      - /tmp/camoufox_*             ← Camoufox temp data
      - /tmp/.com.google.Chrome*    ← Generic Chrome temp files

    Does NOT touch:
      - ~/.cache/ms-playwright/     ← Patchright/Playwright browser binaries (essential!)
      - ~/.cache/camoufox/          ← Camoufox browser binaries (essential!)
      - Any file in the project workspace

    Returns:
        Total bytes freed.
    """
    total_freed = 0

    # --- Patchright / Playwright temp Chrome profiles ---
    patterns = [
        "/tmp/patchright_chromium*", 
        "/tmp/playwright_chromium*", 
        "/tmp/playwright_chromiumdev*",
        "/tmp/uc_*",
        "/tmp/crawl4ai_*",
        "/tmp/camoufox_*",
        "/tmp/.com.google.Chrome*"
    ]
    
    for pattern in patterns:
        for path_str in glob.glob(pattern):
            freed = _safe_remove(Path(path_str))
            if freed > 0:
                logger.debug(f"[DiskCleanup] Removed engine cache: {path_str} ({freed // 1024}KB)")
            total_freed += freed

    # --- Crawl4AI persistent cache ---
    crawl4ai_cache = Path.home() / ".crawl4ai_cache"
    if crawl4ai_cache.exists():
        freed = _safe_remove(crawl4ai_cache)
        if freed > 0:
            logger.info(f"[DiskCleanup] Cleared Crawl4AI persistent cache: {freed // 1024 // 1024}MB freed")
        total_freed += freed

    return total_freed


def check_and_cleanup(threshold_pct: float = 85.0) -> bool:
    """
    Check disk usage. If it exceeds `threshold_pct`, run cleanup.

    This is the main entry point called by HybridEngine before each waterfall.

    Args:
        threshold_pct : Percentage at which cleanup is triggered (default 85%).

    Returns:
        True  if cleanup was triggered (disk was above threshold).
        False if disk is still within acceptable limits.
    """
    pct = _get_disk_usage_pct()

    if pct < threshold_pct:
        return False

    logger.warning(
        f"[DiskCleanup] ⚠️  Disk usage at {pct:.1f}% — above {threshold_pct}% threshold. "
        f"Running automatic cache cleanup..."
    )

    freed = cleanup_browser_caches()
    freed_mb = freed // 1024 // 1024

    pct_after = _get_disk_usage_pct()
    logger.info(
        f"[DiskCleanup] ✅ Cleanup complete — freed ~{freed_mb}MB. "
        f"Disk usage: {pct:.1f}% → {pct_after:.1f}%"
    )

    # Emergency: if disk is still critically full (>95%), emit a CRITICAL alert
    if pct_after > 95:
        try:
            from utils.logger import alert
            alert(
                "CRITICAL",
                f"Disk still critically full after cleanup: {pct_after:.1f}%",
                {"freed_mb": freed_mb, "disk_pct": pct_after},
            )
        except Exception:
            logger.critical(
                f"[DiskCleanup] 🔴 Disk critically full at {pct_after:.1f}% "
                f"even after cleanup. Manual intervention required."
            )

    return True
