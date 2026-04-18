"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/fs.py  —  Filesystem Utilities (Anti-Root Protection)            ║
║                                                                         ║
║  Centralised directory/file creation with world-writable permissions.   ║
║  This prevents the Docker root-ownership lock-in where files created    ║
║  inside a container become inaccessible to the host user.               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
from pathlib import Path


def safe_mkdir(path, mode=0o777) -> Path:
    """
    Create a directory (and parents) with world-writable permissions.
    
    This is the ONLY function that should be used to create directories
    in this project. It ensures that both Docker (root) and the host
    user (youssef) can always read/write/delete the created folders.
    
    Also applies chmod to all parent directories created along the way,
    preventing Docker root-lock on parent folders.
    
    Args:
        path: Directory path (str or Path)
        mode: Permission mode (default: 0o777 = rwxrwxrwx)
    
    Returns:
        Path object of the created directory
    """
    p = Path(path)
    os.makedirs(p, exist_ok=True)
    # chmod the target AND all parent dirs up to project root
    try:
        os.chmod(p, mode)
        for parent in p.parents:
            # Stop at filesystem root or common base paths
            parent_str = str(parent)
            if parent_str in ("/", "/home", "/home/youssef"):
                break
            try:
                os.chmod(parent, mode)
            except OSError:
                break  # Stop if we can't chmod a parent (e.g., /home)
    except OSError:
        pass  # Silently ignore if we can't chmod (e.g. read-only FS)
    return p


def safe_touch(filepath, mode=0o777) -> None:
    """
    After creating/writing a file, grant world-writable permissions.
    
    Call this after saving any file (Excel, CSV, JSON, log) to ensure
    the host user can always manage the output files.
    
    Args:
        filepath: File path (str or Path)
        mode: Permission mode (default: 0o777)
    """
    try:
        if os.path.exists(filepath):
            os.chmod(filepath, mode)
    except OSError:
        pass
