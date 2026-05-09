"""
bootstrap.py — Must be the FIRST import in supervisor.py / any entry-point.

Responsibilities:
  1. Reorder sys.path so site-packages always beat project source dirs
     (prevents numpy/pandas "do not import from source directory" errors).
  2. Apply websockets compatibility shims for uvicorn + nodriver coexistence.

Why this file exists
────────────────────
Docker/PYTHONPATH injects /app/src at position 0, which shadows C-extension
packages (numpy, pandas) installed in site-packages. This file reorders
sys.path so site-packages are ALWAYS resolved first.

Shims applied
─────────────
  Shim 1 — websockets.protocol  → websockets.legacy.protocol
            (nodriver / older uvicorn require the bare name)
  Shim 2 — websockets.asyncio   → synthetic module with .client/.server
            (some uvicorn versions reference this path)
  Shim 3 — websockets.legacy.protocol.{CONNECTING,OPEN,CLOSING,CLOSED}
            In websockets ≥13 these State constants were removed as bare
            module-level names. uvicorn[standard] and some wsproto helpers
            still import them by name, causing ImportError at startup.
"""

import sys
import os
from pathlib import Path

# ── 0. Paths ─────────────────────────────────────────────────────────────
ROOT_DIR = Path(__file__).parent.absolute()
SRC_DIR  = ROOT_DIR / "src"

# ── 1. sys.path sanitization ─────────────────────────────────────────────
# site-packages MUST come before any project directory.
# Docker ENV / PYTHONPATH can inject /app/src at position 0 — we fix it here.
_SITE_PKGS = [p for p in sys.path if "site-packages" in p]
_PROJECT   = [str(ROOT_DIR), str(SRC_DIR)]
_OTHERS    = [p for p in sys.path if "site-packages" not in p and p not in _PROJECT]

# Combine them: site-packages (FIRST) + others + project root/src (LAST)
sys.path[:] = _SITE_PKGS + _OTHERS + _PROJECT

# ── 2. Module-cache eviction for numpy / pandas ───────────────────────────
# If any code ran BEFORE bootstrap (e.g., an eager import at module-load time)
# and partially imported numpy/pandas with a broken path, those broken modules
# are cached in sys.modules. Path fixes have NO effect on cached modules —
# Python returns the same broken object on every subsequent `import numpy`.
#
# Solution: flush every numpy.* and pandas.* entry from the module cache NOW,
# immediately after fixing sys.path. The next `import pandas` will re-resolve
# from scratch using the corrected path and succeed.
for _m in list(sys.modules):
    if _m == "numpy" or _m.startswith("numpy.") \
            or _m == "pandas" or _m.startswith("pandas."):
        sys.modules.pop(_m, None)

# ── 2. Websockets compatibility shims ────────────────────────────────────
try:
    import websockets  # noqa: E402

    # ── Shim 1: websockets.protocol ──────────────────────────────────────
    # nodriver and old uvicorn do: from websockets.protocol import ...
    if not hasattr(websockets, "protocol"):
        try:
            from websockets.legacy import protocol as _lp
            websockets.protocol = _lp
            sys.modules["websockets.protocol"] = _lp
        except (ImportError, AttributeError):
            pass

    # ── Shim 2: websockets.asyncio ───────────────────────────────────────
    # Some uvicorn helpers: from websockets.asyncio.client import connect
    if not hasattr(websockets, "asyncio") or "websockets.asyncio" not in sys.modules:
        try:
            from websockets import client as _wsclient, server as _wsserver

            class _AsyncioShim:  # lightweight synthetic module
                client = _wsclient
                server = _wsserver

            _shim = _AsyncioShim()
            websockets.asyncio = _shim
            sys.modules["websockets.asyncio"]        = _shim          # type: ignore[assignment]
            sys.modules["websockets.asyncio.client"] = _wsclient      # type: ignore[assignment]
            sys.modules["websockets.asyncio.server"] = _wsserver      # type: ignore[assignment]
        except (ImportError, AttributeError):
            pass

    # ── Shim 3: State constants (websockets ≥ 13 breakage) ───────────────
    # In websockets < 13:  websockets.legacy.protocol.CONNECTING = 0 (int)
    # In websockets ≥ 13:  those names were REMOVED from the module namespace.
    # uvicorn[standard] internals (wsproto / websockets WebSocket handler) do:
    #   from websockets.legacy.protocol import CONNECTING
    # → ImportError: cannot import name 'CONNECTING'
    #
    # Fix: inject the missing names directly into the legacy.protocol module.
    try:
        from websockets.legacy import protocol as _lp2  # noqa: E402

        # websockets ≥ 13 uses an IntEnum called State (or similar).
        # Try to reconstruct the bare int-like constants from whatever is available.
        def _get_state_value(name: str, fallback: int) -> int:
            """Resolve a State constant regardless of websockets version."""
            # Pattern 1: websockets 10–12 — bare int constants on the module
            val = getattr(_lp2, name, None)
            if val is not None and isinstance(val, int):
                return val
            # Pattern 2: websockets 12 — State enum
            State = getattr(_lp2, "State", None)
            if State is not None:
                member = getattr(State, name, None)
                if member is not None:
                    return int(member)
            # Pattern 3: websockets 13+ — connection.State (moved module)
            try:
                from websockets.connection import State as _S
                member = getattr(_S, name, None)
                if member is not None:
                    return int(member)
            except ImportError:
                pass
            return fallback

        for _cname, _fallback in [
            ("CONNECTING", 0),
            ("OPEN",       1),
            ("CLOSING",    2),
            ("CLOSED",     3),
        ]:
            if not hasattr(_lp2, _cname):
                setattr(_lp2, _cname, _get_state_value(_cname, _fallback))

    except (ImportError, AttributeError):
        # websockets.legacy doesn't exist at all (very old or future version)
        # → nothing we can do here; uvicorn will fail on its own terms
        print("⚠️ websockets.legacy doesn't exist at all (very old or future version)")
        pass

except ImportError:
    # websockets not installed at all — not our problem, skip all shims
    print("⚠️ websockets not installed at all — not our problem, skip all shims")
    pass
