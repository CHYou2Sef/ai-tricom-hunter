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

"""
╔══════════════════════════════════════════════════════════════════════════╗
║  common/proxy_manager.py                                                 ║
║                                                                          ║
║  Proxy Pool Manager with State Machine & Health Tracking                 ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Manages a rotating pool of HTTP proxies to prevent IP bans.           ║
║    Tracks proxy health via a state machine: HEALTHY → WARN → BAN         ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    1. Fetches proxies from premium .env list OR free public sources      ║
║    2. Validates proxy URLs (blocks SSRF/private ranges)                  ║
║    3. get_proxy() returns next healthy proxy from shuffled pool          ║
║    4. mark_error() advances state machine; BAN triggers rotation         ║
║    5. Exponential backoff between rotations: 1s → 2s → 4s → 8s → 16s   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import random
import asyncio
import time
import httpx
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
    HEALTHY   = "HEALTHY"
    WARN      = "WARN"
    QUARANTINE = "QUARANTINE"  # Temporary ban (e.g. 1 hour)
    BAN       = "BAN"         # Permanent or long-term ban
    ROTATING  = "ROTATING"


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
    quarantine_until: Optional[float] = None


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
    Now fully asynchronous to prevent event loop blocking.
    """

    def __init__(self):
        self._records: Dict[str, ProxyRecord] = {}   # address → ProxyRecord
        self._active_pool: List[str]           = []   # available (HEALTHY/WARN) addresses
        self._rotation_attempt: int            = 0    # backoff counter
        self._lock = asyncio.Lock()

    # ── Public API ────────────────────────────────────────────────────────

    async def get_proxy(self) -> Optional[str]:
        """
        Return the next available healthy proxy.
        Refills from remote sources if pool is empty.
        Returns None to signal direct (un-proxied) connection.
        """
        async with self._lock:
            if not self._active_pool:
                await self._refill_pool_locked()

            now = asyncio.get_event_loop().time()

            # Pick first available address from pool.
            # Skip proxies still in quarantine.
            while self._active_pool:
                addr = self._active_pool.pop(0)
                record = self._records.get(addr)
                if not record:
                    continue

                # 🩺 QUARANTINE CHECK: release quarantine when time has elapsed
                if record.state == ProxyState.QUARANTINE:
                    if record.quarantine_until and now >= record.quarantine_until:
                        logger.info(f"[ProxyManager] 🏥 Proxy {addr} recovered from quarantine.")
                        record.state = ProxyState.HEALTHY
                        record.error_count = 0
                        record.quarantine_until = None
                    else:
                        # Still quarantined — skip
                        continue

                if record.state not in (ProxyState.BAN, ProxyState.ROTATING):
                    logger.info(f"[ProxyManager] 🔌 Using proxy: {addr} (state={record.state.value})")
                    return addr

            logger.warning("[ProxyManager] ⚠️ No healthy proxies available. Running direct.")
            return None

    async def mark_error(self, address: str, status_code: int = 0) -> ProxyState:
        """
        Record a failed request for this proxy and advance its state machine.
        """
        async with self._lock:
            if address not in self._records:
                # First time we see this proxy — create its record
                self._records[address] = ProxyRecord(address=address)

            record = self._records[address]
            record.error_count += 1
            record.last_status  = status_code

            if record.error_count >= config.PROXY_BAN_THRESHOLD:
                await self._ban_proxy_locked(record)

            elif record.error_count >= config.PROXY_WARN_THRESHOLD:
                if record.state == ProxyState.HEALTHY:
                    record.state = ProxyState.WARN
                    logger.warning(
                        f"[ProxyManager] ⚠️ WARN — proxy {address} "
                        f"({record.error_count} errors, last HTTP {status_code})"
                    )
                    
                if getattr(config, 'PROXY_PREEMPTIVE_ROTATE_ON_WARN', True):
                    logger.warning(f"[ProxyManager] Preemptive rotation triggered for {address} to preserve health.")
                    await self._ban_proxy_locked(record)
            else:
                logger.debug(
                    f"[ProxyManager] Error #{record.error_count} on {address} "
                    f"(HTTP {status_code})"
                )

            return record.state

    async def mark_banned(self, address: str) -> None:
        """Force-ban a proxy immediately (e.g. on explicit 429 ban message)."""
        async with self._lock:
            if address not in self._records:
                self._records[address] = ProxyRecord(address=address)
            await self._ban_proxy_locked(self._records[address])

    async def get_proxy_stats(self) -> Dict[str, dict]:
        """Return a dict of all tracked proxies and their current state."""
        async with self._lock:
            return {
                addr: {
                    "state":        rec.state.value,
                    "error_count":  rec.error_count,
                    "last_status":  rec.last_status,
                }
                for addr, rec in self._records.items()
            }

    # ── Internal Methods ──────────────────────────────────────────────────

    async def _ban_proxy_locked(self, record: ProxyRecord) -> None:
        """Transition a proxy to QUARANTINE or BAN state and trigger an exponential backoff rotation."""
        if record.state in (ProxyState.BAN, ProxyState.QUARANTINE):
            return  # Already restricted

        # 🛡️ QUARANTINE: Default to 1 hour (3600s) for hard WAF blocks
        quarantine_duration = getattr(config, "PROXY_QUARANTINE_SEC", 3600)
        now = asyncio.get_event_loop().time()

        record.state = ProxyState.QUARANTINE
        record.banned_at = now
        record.quarantine_until = now + quarantine_duration

        logger.error(
            f"[ProxyManager] 🚫 QUARANTINE — proxy {record.address} "
            f"({record.error_count} errors). Restricted until {time.strftime('%H:%M:%S', time.localtime(time.time() + quarantine_duration))}"
        )
        await self._rotate_with_backoff_locked()

    async def _rotate_with_backoff_locked(self) -> None:
        """
        Exponential backoff before grabbing the next proxy.
        """
        delays = config.PROXY_BACKOFF_DELAYS
        idx    = min(self._rotation_attempt, len(delays) - 1)
        delay  = delays[idx]

        logger.info(
            f"[ProxyManager] ♻️  Rotating — backoff step #{self._rotation_attempt} "
            f"→ waiting {delay}s before next proxy"
        )
        await asyncio.sleep(delay)
        self._rotation_attempt += 1

        # Refill pool if empty after rotation
        if not self._active_pool:
            await self._refill_pool_locked()

    def _validate_proxy_url(self, url: str) -> bool:
        """Validate proxy URL format to prevent SSRF/injection."""
        from urllib.parse import urlparse
        try:
            parsed = urlparse(url)
            ALLOWED_SCHEMES = ('http', 'https')
            if parsed.scheme not in ALLOWED_SCHEMES:
                return False
            if not parsed.hostname or len(parsed.hostname) > 253:
                return False
            if parsed.port and not (1 <= parsed.port <= 65535):
                return False
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

    async def _refill_pool_locked(self) -> None:
        """Fetch fresh proxies from all public sources and reset the pool."""
        logger.info("🔄 [ProxyManager] Loading proxy pool...")
        fetched: set = set()

        # 1. 🌟 PREMIUM RESIDENTIAL PROXIES
        # CRITICAL: No free proxy fallback — free proxies are instantly banned by Google
        # and cause all searches to return NO TEL. If RESIDENTIAL_PROXIES_ENV is empty,
        # the pool stays empty and the system runs direct (no proxy) rather than
        # silently degrading with banned datacenter IPs.
        if RESIDENTIAL_PROXIES_ENV:
            logger.info("💎 [ProxyManager] Loading Premium Residential Proxies from .env...")
            for proxy_url in RESIDENTIAL_PROXIES_ENV.split(","):
                clean_url = proxy_url.strip()
                if clean_url and self._validate_proxy_url(clean_url):
                    fetched.add(clean_url)
        else:
            logger.warning(
                "⚠️ [ProxyManager] RESIDENTIAL_PROXIES is empty — "
                "no proxy will be used (running direct). "
                "Free proxy fallback is DISABLED because datacenter IPs are banned by Google."
            )

        # Register new proxies
        for addr in fetched:
            if addr not in self._records:
                self._records[addr] = ProxyRecord(address=addr)

        # Rebuild active pool
        healthy = [
            addr for addr, rec in self._records.items()
            if rec.state in (ProxyState.HEALTHY, ProxyState.WARN)
        ]
        random.shuffle(healthy)
        self._active_pool = healthy

        logger.info(f"✅ [ProxyManager] Pool ready: {len(self._active_pool)} proxies.")
        self._rotation_attempt = 0


# ─────────────────────────────────────────────────────────────────────────────
# MODULE-LEVEL SINGLETON — updated to be async
# ─────────────────────────────────────────────────────────────────────────────

_global_proxy_manager = ProxyManager()


async def get_next_proxy() -> Optional[str]:
    """Get the next healthy proxy from the global pool (Async)."""
    return await _global_proxy_manager.get_proxy()


async def report_proxy_error(address: str, status_code: int = 0) -> ProxyState:
    """Notify the global manager that a proxy returned an error (Async)."""
    return await _global_proxy_manager.mark_error(address, status_code)


async def force_ban_proxy(address: str) -> None:
    """Immediately ban a proxy (Async)."""
    await _global_proxy_manager.mark_banned(address)


async def get_proxy_stats() -> Dict[str, dict]:
    """Return the current state of all tracked proxies (Async)."""
    return await _global_proxy_manager.get_proxy_stats()
