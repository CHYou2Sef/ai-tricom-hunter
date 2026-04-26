"""
╔══════════════════════════════════════════════════════════════════════════╗
║  core/singleton.py                                                       ║
║                                                                          ║
║  Process-level singleton enforcement using POSIX file locks (fcntl).     ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Ensures only ONE instance of the agent worker runs at a time.         ║
║    Prevents duplicate processing and resource contention.                ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    Creates a .lock file in the work directory.                           ║
║    Uses fcntl.LOCK_EX | fcntl.LOCK_NB for non-blocking exclusive lock.   ║
║    If lock fails, reads PID from file and exits with error.              ║
║    Lock is automatically released when process terminates.               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import fcntl
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

def ensure_singleton(lock_name: str, work_dir: Path):
    """
    Ensures that only one instance of the script is running.
    Uses a file lock that is automatically released when the process exits.
    """
    lock_file = work_dir / f".{lock_name}.lock"
    
    # Try to open the lock file
    try:
        f = open(lock_file, 'w')
        # Try to acquire an exclusive lock without blocking (LOCK_EX | LOCK_NB)
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        
        # Write the current PID to the lock file for debugging
        f.write(str(os.getpid()))
        f.flush()
        
        # We must keep the file object open to maintain the lock
        # Attaching it to a global variable or return it so it doesn't get GC'd
        return f
    except (IOError, OSError):
        pid = "unknown"
        try:
            with open(lock_file, 'r') as rf:
                pid = rf.read().strip()
        except:
            pass
            
        logger.error(f"❌ [Singleton] Another instance of '{lock_name}' is already running (PID: {pid}).")
        logger.error(f"   Check running processes or use 'docker logs -f tricom_ai_agent' if in Docker.")
        sys.exit(1)
