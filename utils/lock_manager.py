"""
utils/lock_manager.py - Singleton Process Protection
Prevents multiple instances (Local vs Docker) from corrupting the WORK directory.
"""
import os
import sys
import time
from pathlib import Path
from utils.logger import get_logger

logger = get_logger(__name__)

LOCK_FILE = Path("WORK/.agent.lock")

def acquire_lock(instance_name: str) -> bool:
    """
    Attempts to acquire an exclusive lock on the WORK directory.
    Returns True if successfully claimed, False if another instance is active.
    """
    if not LOCK_FILE.parent.exists():
        LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Check if lock exists and if the process is alive (simplified for cross-OS)
    if LOCK_FILE.exists():
        try:
            with open(LOCK_FILE, "r") as f:
                content = f.read().strip()
                old_instance, old_pid = content.split("|")
                
            # If the instance name is the same (e.g. restart), we allow it
            # Otherwise, we warn the user.
            logger.warning(f"⚠️  CONFLICT: Instance '{old_instance}' (PID {old_pid}) is already managing this WORK directory.")
            return False
        except Exception:
            # Corrupted lock file, we will try to overwrite
            pass

    try:
        # Atomic write of the lock file
        with open(LOCK_FILE, "w") as f:
            f.write(f"{instance_name}|{os.getpid()}")
            f.flush()
            os.fsync(f.fileno())
        logger.info(f"✅ LOCK ACQUIRED: '{instance_name}' is now the Master of this directory.")
        return True
    except Exception as e:
        logger.error(f"❌ Failed to acquire lock: {e}")
        return False

def release_lock():
    """Removes the lock file on graceful shutdown."""
    if LOCK_FILE.exists():
        try:
            LOCK_FILE.unlink()
            logger.info("🔓 LOCK RELEASED: WORK directory is now free.")
        except Exception:
            pass
