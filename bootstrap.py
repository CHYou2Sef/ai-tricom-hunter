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

# ── Websockets Incompatibility Shim ───────────────────────────────────
# Fixes: ModuleNotFoundError: No module named 'websockets.protocol'
# Fixes: ModuleNotFoundError: No module named 'websockets.asyncio'
# This happens in environments with mismatched websockets/nodriver versions.
try:
    import websockets
    # Shim 1: websockets.protocol -> websockets.legacy.protocol
    if not hasattr(websockets, "protocol"):
        try:
            from websockets.legacy import protocol
            websockets.protocol = protocol
            sys.modules["websockets.protocol"] = protocol
        except (ImportError, AttributeError):
            pass

    # Shim 2: websockets.asyncio -> websockets.client/server
    if not hasattr(websockets, "asyncio"):
        try:
            from websockets import client, server
            class AsyncioShim:
                def __init__(self):
                    self.client = client
                    self.server = server
            shim = AsyncioShim()
            websockets.asyncio = shim
            sys.modules["websockets.asyncio"] = shim
            sys.modules["websockets.asyncio.client"] = client
            sys.modules["websockets.asyncio.server"] = server
        except (ImportError, AttributeError):
            pass
except ImportError:
    pass
