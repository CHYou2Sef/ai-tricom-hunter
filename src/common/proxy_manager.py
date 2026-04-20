"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/proxy_manager.py                                                  ║
║                                                                          ║
║  TASK 3 from GEMINI.md — Proxy & IP Rotation Strategy                   ║
║                                                                          ║
║  Implements the full proxy state machine:                                ║
║    HEALTHY → (warn_threshold errors) → WARN                              ║
║    WARN    → (ban_threshold errors)  → BAN  → ROTATE → HEALTHY           ║
║                                                                          ║
║  Backoff on rotation: 1s → 2s → 4s → 8s → 16s → 32s (exponential)     ║
║  Binds one proxy per browser context, never globally.                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import random
import time
import urllib.request
import concurrent.futures
from enum import Enum
from dataclasses import dataclass, field
from typing import Optional, List, Dict

from core import config
from core.logger import get_logger

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# PROXY STATE MACHINE
# ─────────────────────────────────────────────────────────────────────────────

class ProxyState(Enum):
    """
    A proxy moves through these states based on accumulated error counts.

    HEALTHY → normal operation, no issues detected
    WARN    → multiple errors seen; still in use but flagged
    BAN     → too many errors; taken off the pool, rotation triggered
    ROTATING→ transient state while we switch to a fresh proxy
    """
    HEALTHY  = "HEALTHY"
    WARN     = "WARN"
    BAN      = "BAN"
    ROTATING = "ROTATING"


@dataclass
class ProxyRecord:
    """
    Tracks the health and history of a single proxy address.

    Attributes:
        address     : Full proxy URL, e.g. "http://1.2.3.4:8080"
        state       : Current ProxyState
        error_count : Cumulative error count (resets after rotate)
        last_status : HTTP status code of the last error (403, 429, etc.)
        banned_at   : Unix timestamp when this proxy was banned
    """
    address: str
    state: ProxyState = ProxyState.HEALTHY
    error_count: int = 0
    last_status: int = 0
    banned_at: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────────────
# PROXY SOURCES (Residential / Free Fallbacks)
# ─────────────────────────────────────────────────────────────────────────────

# Optional: List your premium residential proxies in your .env file
# Format: RESIDENTIAL_PROXIES=http://user:pass@ip:port,http://user:pass@ip2:port
RESIDENTIAL_PROXIES_ENV = os.getenv("RESIDENTIAL_PROXIES", "")

FREE_PROXY_SOURCES = [
    # 1. Proxyscrape
    "https://api.proxyscrape.com/v2/?request=getproxies&protocol=http&timeout=10000&country=all&ssl=all&anonymity=all",
    # 2. Geonode
    "https://proxylist.geonode.com/api/proxy-list?limit=100&page=1&sort_by=lastChecked&sort_type=desc&protocols=http,https",
    # 3. GitHub list
    "https://raw.githubusercontent.com/TheSpeedX/PROXY-List/master/http.txt",
]


class ProxyManager:
    """
    Manages a pool of proxies with full state-machine lifecycle tracking.

    Usage:
        pm = ProxyManager()
        proxy = pm.get_proxy()          # Attach to a new browser context
        ...
        pm.mark_error(proxy, 429)       # 429 received
        pm.mark_error(proxy, 403)       # 403 received → may trigger BAN
    """

    def __init__(self):
        self._records: Dict[str, ProxyRecord] = {}   # address → ProxyRecord
        self._active_pool: List[str]           = []   # available (HEALTHY/WARN) addresses
        self._rotation_attempt: int            = 0    # backoff counter
        self._lock = concurrent.futures.ThreadPoolExecutor(max_workers=1)

    # ── Public API ────────────────────────────────────────────────────────

    def get_proxy(self) -> Optional[str]:
        """
        Return the next available HEALTHY proxy address.
        Fetches from public sources if the pool is empty.
        Returns None if no proxies are available (run direct).
        """
        if not self._active_pool:
            self._refill_pool()

        # Pick first available address from pool
        while self._active_pool:
            addr = self._active_pool.pop(0)
            record = self._records.get(addr)
            if record and record.state not in (ProxyState.BAN, ProxyState.ROTATING):
                logger.info(f"[ProxyManager] 🔌 Using proxy: {addr} (state={record.state.value})")
                return addr

        logger.warning("[ProxyManager] ⚠️ No healthy proxies available. Running direct.")
        return None

    def mark_error(self, address: str, status_code: int = 0) -> ProxyState:
        """
        Record a failed request for this proxy and advance its state machine.

        State transitions:
          HEALTHY  → WARN  when error_count ≥ PROXY_WARN_THRESHOLD
          WARN     → BAN   when error_count ≥ PROXY_BAN_THRESHOLD
          BAN      → triggers auto-rotation with exponential backoff

        Args:
            address     : Proxy address string
            status_code : HTTP response code (403, 429, 0 for connection error)

        Returns:
            The new ProxyState after the update
        """
        if address not in self._records:
            # First time we see this proxy — create its record
            self._records[address] = ProxyRecord(address=address)

        record = self._records[address]
        record.error_count += 1
        record.last_status  = status_code

        if record.error_count >= config.PROXY_BAN_THRESHOLD:
            self._ban_proxy(record)

        elif record.error_count >= config.PROXY_WARN_THRESHOLD:
            if record.state == ProxyState.HEALTHY:
                record.state = ProxyState.WARN
                logger.warning(
                    f"[ProxyManager] ⚠️ WARN — proxy {address} "
                    f"({record.error_count} errors, last HTTP {status_code})"
                )
                
            if getattr(config, 'PROXY_PREEMPTIVE_ROTATE_ON_WARN', True):
                logger.warning(f"[ProxyManager] Preemptive rotation triggered for {address} to preserve health.")
                self._ban_proxy(record)
        else:
            logger.debug(
                f"[ProxyManager] Error #{record.error_count} on {address} "
                f"(HTTP {status_code})"
            )

        return record.state

    def mark_banned(self, address: str) -> None:
        """Force-ban a proxy immediately (e.g. on explicit 429 ban message)."""
        if address not in self._records:
            self._records[address] = ProxyRecord(address=address)
        self._ban_proxy(self._records[address])

    def get_proxy_stats(self) -> Dict[str, dict]:
        """
        Return a dict of all tracked proxies and their current state.
        Useful for the monitoring / alert system (Task 6).

        Returns:
            {
              "http://1.2.3.4:8080": {
                  "state": "WARN",
                  "error_count": 11,
                  "last_status": 403
              },
              ...
            }
        """
        return {
            addr: {
                "state":        rec.state.value,
                "error_count":  rec.error_count,
                "last_status":  rec.last_status,
            }
            for addr, rec in self._records.items()
        }

    # ── Internal Methods ──────────────────────────────────────────────────

    def _ban_proxy(self, record: ProxyRecord) -> None:
        """Transition a proxy to BAN state and trigger an exponential backoff rotation."""
        if record.state == ProxyState.BAN:
            return  # Already banned, ignore

        record.state     = ProxyState.BAN
        record.banned_at = time.time()

        logger.error(
            f"[ProxyManager] 🚫 BAN — proxy {record.address} "
            f"({record.error_count} errors). Triggering rotation."
        )
        self._rotate_with_backoff()

    def _rotate_with_backoff(self) -> None:
        """
        Exponential backoff before grabbing the next proxy.
        Delays follow config.PROXY_BACKOFF_DELAYS: [1, 2, 4, 8, 16, 32] seconds.
        After the last step, it loops back to the first delay.
        """
        delays = config.PROXY_BACKOFF_DELAYS
        idx    = min(self._rotation_attempt, len(delays) - 1)
        delay  = delays[idx]

        logger.info(
            f"[ProxyManager] ♻️  Rotating — backoff step #{self._rotation_attempt} "
            f"→ waiting {delay}s before next proxy"
        )
        time.sleep(delay)
        self._rotation_attempt += 1

        # Refill pool if empty after rotation
        if not self._active_pool:
            self._refill_pool()

def _validate_proxy_url(self, url: str) -> bool:
    """
    Validate proxy URL format to prevent SSRF/injection.
    Blocks local addresses, invalid schemes/ports.
    """
    from urllib.parse import urlparse
    try:
        parsed = urlparse(url)
        ALLOWED_SCHEMES = ('http', 'https')  # socks blocked for security
        if parsed.scheme not in ALLOWED_SCHEMES:
            return False
        if not parsed.hostname or len(parsed.hostname) > 253:
            return False
        if parsed.port and not (1 <= parsed.port <= 65535):
            return False
        # Block RFC-1918 private ranges + loopback
        PRIVATE_RANGES = ('localhost', '127.0.0.1', '0.0.0.0', '::1', 
                         '10.', '172.16.', '172.17.', '172.18.', '172.19.', 
                         '172.20.', '172.21.', '172.22.', '172.23.', '172.24.', 
                         '172.25.', '172.26.', '172.27.', '172.28.', '172.29.', 
                         '172.30.', '172.31.', '192.168.')
        if any(parsed.hostname.startswith(r) for r in PRIVATE_RANGES):
            return False
        return True
    except Exception:
        return False

    def _refill_pool(self) -> None:
        """Fetch fresh proxies from all public sources and reset the pool."""
        logger.info("🔄 [ProxyManager] Loading proxy pool...")
        fetched: set = set()

        # 1. 🌟 PREMIUM RESIDENTIAL PROXIES (Highest Priority)
        if RESIDENTIAL_PROXIES_ENV:
            logger.info("💎 [ProxyManager] Loading Premium Residential Proxies from .env...")
            for proxy_url in RESIDENTIAL_PROXIES_ENV.split(","):
                clean_url = proxy_url.strip()
                if clean_url and self._validate_proxy_url(clean_url):
                    fetched.add(clean_url)
        else:
            # 2. 🏴‍☠️ FREE PROXIES (Fallback if no Premium setup)
            logger.info("⚠️ [ProxyManager] No RESIDENTIAL_PROXIES found in .env. Falling back to free public proxies (Unstable)...")
            for url in FREE_PROXY_SOURCES:
                try:
                    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
with urllib.request.urlopen(req, timeout=5, context=ssl.create_default_context()) as resp:
                        content = resp.read().decode("utf-8")

                        if "geonode.com" in url:
                            data = json.loads(content)
                            for item in data.get("data", []):
                                ip   = item.get("ip")
                                port = item.get("port")
                                if ip and port:
                                    proxy_str = f"http://{ip}:{port}"
                                    if self._validate_proxy_url(proxy_str):
                                        fetched.add(proxy_str)

                        else:  # proxyscrape or GitHub plain text
                            for line in content.splitlines():
                                line = line.strip()
                                if line and ":" in line:
                                    proxy_str = f"http://{line}" if "http" not in line else line
                                    if self._validate_proxy_url(proxy_str):
                                        fetched.add(proxy_str)

                except Exception as exc:
                    logger.debug(f"[ProxyManager] Source failed ({url}): {exc}")

        # Register new proxies (don't overwrite known ones that are just WARN)
        for addr in fetched:
            if addr not in self._records:
                self._records[addr] = ProxyRecord(address=addr)

        # Rebuild active pool — only HEALTHY and WARN proxies
        healthy = [
            addr for addr, rec in self._records.items()
            if rec.state in (ProxyState.HEALTHY, ProxyState.WARN)
        ]
        random.shuffle(healthy)
        self._active_pool = healthy

        logger.info(f"✅ [ProxyManager] Pool ready: {len(self._active_pool)} proxies.")
        # Reset rotation counter on successful refill
        self._rotation_attempt = 0


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON — imported by all browser agents
# ─────────────────────────────────────────────────────────────────────────────

_global_proxy_manager = ProxyManager()


def get_next_proxy() -> Optional[str]:
    """Get the next healthy proxy from the global pool."""
    return _global_proxy_manager.get_proxy()


def report_proxy_error(address: str, status_code: int = 0) -> ProxyState:
    """Notify the global manager that a proxy returned an error."""
    return _global_proxy_manager.mark_error(address, status_code)


def force_ban_proxy(address: str) -> None:
    """Immediately ban a proxy (use on confirmed bans)."""
    _global_proxy_manager.mark_banned(address)


def get_proxy_stats() -> Dict[str, dict]:
    """Return the current state of all tracked proxies."""
    return _global_proxy_manager.get_proxy_stats()
