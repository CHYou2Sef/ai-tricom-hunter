import sys
import os
from pathlib import Path

# Absolute path to the PROJECT ROOT
ROOT_DIR = Path(__file__).parent.absolute()
SRC_DIR = ROOT_DIR / "src"

# Add directories to sys.path
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

# Pre-setup critical paths
try:
    from core import config
    for d in [config.WORK_DIR, config.INCOMING_DIR, config.LOG_DIR]:
        d.mkdir(parents=True, exist_ok=True)
except Exception:
    pass
