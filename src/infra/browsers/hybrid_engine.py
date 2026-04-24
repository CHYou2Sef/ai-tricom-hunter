"""
╔════════════════════════════════════════════════════════════════════════╗
║  browser/hybrid_engine.py                                              ║
║                                                                        ║
║  Central routing brain — selects the right scraping tier based on      ║
║  the target URL's protection level, then escalates on failure.         ║
║                                                                        ║
║  Decision matrix (5-Tier Waterfall — docs/Gemini.md blueprint):        ║
║  ┌──────────────────────────────────────┬──────────────────────────┐  ║
║  │ Target Type                          │ Agent                    │  ║
║  ├──────────────────────────────────────┼──────────────────────────┤  ║
║  │ Default / standard sites             │ Tier 1: SeleniumBase UC  │  ║
║  │ Internal / no protection             │ Tier 2: PatchrightAgent  │  ║
║  │ Cloudflare / LinkedIn / Facebook     │ Tier 3: NodriverAgent    │  ║
║  │ Amazon / Fnac / hardened e-commerce  │ Tier 4: Crawl4AIAgent    │  ║
║  │ ALL Chrome tiers exhausted           │ Tier 5: CamoufoxAgent 🦊 │  ║
║  └──────────────────────────────────────┴──────────────────────────┘  ║
║                                                                        ║
║  Escalation waterfall (DEFAULT_TIER=1):                                ║
║    Tier 1 (SeleniumBase UC) fails                                      ║
║      → Tier 2 (Patchright/Chrome stealth) fails                       ║
║        → Tier 3 (Nodriver/Chrome CDP) fails                           ║
║          → Tier 4 (Crawl4AI/Chrome managed) fails                     ║
║            → Tier 5 (Camoufox/Firefox) — last resort                  ║
║              → ALL FAIL: Circuit Breaker OPEN → pause 300s            ║
╚════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
from typing import Optional, Dict, Any, List

from core import config
from core.logger import get_logger, alert
from core.observability import SCRAPING_RESULTS
from common.metrics import get_telemetry

logger = get_logger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# URL TIER CLASSIFIER
# ─────────────────────────────────────────────────────────────────────────────

def classify_url(url: str) -> int:
    """
    Determine which scraping tier best suits the target URL.

    Decision logic:
      1. Matches config.HYBRID_TIER3_DOMAINS → Tier 3 (hardened)
      2. Matches config.HYBRID_TIER2_DOMAINS → Tier 2 (stealth)
      3. Default                             → Tier 1 (fast)

    Args:
        url : Target URL string

    Returns:
        int : 1, 2, or 3
    """
    url_lower = url.lower()

    for domain in config.HYBRID_TIER3_DOMAINS:
        if domain in url_lower:
            logger.debug(f"[HybridEngine] Classified as Tier 3: {domain} found in {url}")
            return 3

    for domain in config.HYBRID_TIER2_DOMAINS:
        if domain in url_lower:
            logger.debug(f"[HybridEngine] Classified as Tier 2: {domain} found in {url}")
            return 2

    logger.debug(f"[HybridEngine] Classified as Tier {config.HYBRID_DEFAULT_TIER} (default): {url}")
    return config.HYBRID_DEFAULT_TIER


# ─────────────────────────────────────────────────────────────────────────────
# HYBRID ENGINE  (async context manager)
# ─────────────────────────────────────────────────────────────────────────────

class HybridAutomationEngine:
    """
    The main orchestrator. Manages all three tier agents as a pool
    and routes each task to the appropriate one.
    """
    # ── Configuration & Resource Locks ─────────────────────────────────────
    _CB_THRESHOLD = 5      # Consecutive failures before opening circuit
    _CB_PAUSE_SEC  = 300   # 5 minutes pause
    
    # Tier 4 (Camoufox/Firefox) is extremely heavy. We limit it to 
    # a single concurrent instance across ALL workers to save RAM.
    _tier4_global_lock = asyncio.Lock()
    
    _TIER_NAMES = {
        0: "selenium_legacy",
        1: "seleniumbase",
        2: "patchright",
        3: "nodriver",
        4: "crawl4ai",
        5: "camoufox",
    }
    
    def __init__(self, worker_id: int = 0):
        self._worker_id = worker_id
        self._tier0: Optional[object] = None   # SeleniumAgent      (Legacy/Benchmark)
        self._tier1: Optional[object] = None   # SeleniumBaseAgent  (UC Driver — Tier 1)
        self._tier2: Optional[object] = None   # PatchrightAgent    (Chrome stealth)
        self._tier3: Optional[object] = None   # NodriverAgent      (Chrome CDP)
        self._tier4: Optional[object] = None   # Crawl4AIAgent      (Chrome managed)
        self._tier5: Optional[object] = None   # CamoufoxAgent      (Firefox anti-detect)
        self._current_tier = 1

        # ── Circuit Breaker state ─────────────────────────────────────────────
        # Prevents infinite retry storms when ALL tiers fail due to IP banning.
        self._current_tier = config.HYBRID_DEFAULT_TIER
        self._last_successful_tier: Optional[int] = None
        self._circuit_breaker_open = False
        self._circuit_breaker_until = 0.0
        self._consecutive_failures = 0
        self._last_target_url: Optional[str] = None  # For re-navigation catch-up
        self.current_row_index: int = 0             # Track current row for telemetry
        self.last_successful_tier_used: Optional[int] = None # For per-row export

        self._stats: Dict[int, Dict[str, Any]] = {
            0: {"attempts": 0, "successes": 0, "total_ms": 0},  # SeleniumAgent (legacy)
            1: {"attempts": 0, "successes": 0, "total_ms": 0},  # SeleniumBase UC
            2: {"attempts": 0, "successes": 0, "total_ms": 0},  # Patchright
            3: {"attempts": 0, "successes": 0, "total_ms": 0},  # Nodriver
            4: {"attempts": 0, "successes": 0, "total_ms": 0},  # Crawl4AI
            5: {"attempts": 0, "successes": 0, "total_ms": 0},  # Camoufox
        }

    @property
    def worker_id(self):
        return self._worker_id

    # ── Context manager support ────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.stop_all()
        
    # ── Tier management ────────────────────────────────────────────────────

    async def start_tier(self, tier: int) -> bool:
        try:
            # 1. Check if existing agent is alive
            agent_map = {
                0: self._tier0, 1: self._tier1, 2: self._tier2,
                3: self._tier3, 4: self._tier4, 5: self._tier5,
            }
            agent = agent_map.get(tier)
            if agent:
                try:
                    await asyncio.wait_for(agent.get_page_source(), timeout=2)
                except Exception:
                    logger.warning(f"[HybridEngine] Tier {tier} appears STALE. Restarting...")
                    await self.stop_tier(tier)
                    agent = None

            # ── Tier 0: Legacy SeleniumAgent (ucd benchmark) ───────────────
            if tier == 0 and not self._tier0:
                from infra.browsers.selenium_agent import SeleniumAgent
                self._tier0 = SeleniumAgent(worker_id=self._worker_id)
                await self._tier0.start()
                logger.info(f"[HybridEngine] ✅ Tier 0 (SeleniumUCD/Legacy) started for worker {self.worker_id}.")

            # ── Tier 1: SeleniumBase UC Driver (PRIMARY) ───────────────────
            elif tier == 1 and not self._tier1:
                if not getattr(config, "SELENIUMBASE_ENABLED", True):
                    logger.warning("[HybridEngine] Tier 1 (SeleniumBase) is DISABLED in config. Skipping.")
                    return False
                from infra.browsers.seleniumbase_agent import SeleniumBaseAgent
                self._tier1 = SeleniumBaseAgent(worker_id=self._worker_id)
                await self._tier1.start()
                logger.info(f"[HybridEngine] ✅ Tier 1 ⭐ (SeleniumBase UC) started for worker {self.worker_id}.")

            # ── Tier 2: PatchrightAgent (Chrome stealth) ───────────────────
            elif tier == 2 and not self._tier2:
                from infra.browsers.patchright_agent import PatchrightAgent
                self._tier2 = PatchrightAgent(worker_id=self._worker_id)
                await self._tier2.start()
                logger.info(f"[HybridEngine] ✅ Tier 2 (Patchright/Chrome) started for worker {self.worker_id}.")

            # ── Tier 3: NodriverAgent (Chrome CDP) ────────────────────────
            elif tier == 3 and not self._tier3:
                from infra.browsers.nodriver_agent import NodriverAgent
                self._tier3 = NodriverAgent(worker_id=self._worker_id)
                await self._tier3.start()
                logger.info(f"[HybridEngine] ✅ Tier 3 (Nodriver/Chrome CDP) started for worker {self.worker_id}.")

            # ── Tier 4: Crawl4AIAgent (Chrome managed) ────────────────────
            elif tier == 4 and not self._tier4:
                from infra.browsers.crawl4ai_agent import Crawl4AIAgent
                self._tier4 = Crawl4AIAgent()
                await self._tier4.start()
                logger.info(f"[HybridEngine] ✅ Tier 4 (Crawl4AI/Chrome) started for worker {self.worker_id}.")

            # ── Tier 5: CamoufoxAgent (Firefox anti-detect — last resort) ─
            elif tier == 5 and not self._tier5:
                if not config.CAMOUFOX_ENABLED:
                    logger.warning("[HybridEngine] Tier 5 (Camoufox) is DISABLED in config. Skipping.")
                    return False
                async with self._tier4_global_lock:  # reuse global lock for Camoufox
                    from infra.browsers.camoufox_agent import CamoufoxAgent
                    self._tier5 = CamoufoxAgent(worker_id=self._worker_id)
                    await self._tier5.start()
                    logger.info(
                        f"[HybridEngine] ✅ Tier 5 🦊 (Camoufox) started for worker {self.worker_id} (Global Lock Acquired)."
                    )

            return True
        except ImportError as ie:
            logger.error(f"  ❌ [HybridEngine] Tier {tier} is NOT INSTALLED! Skip to next available tier.")
            logger.warning(f"     Run: pip install {ie.name}")
            return False
        except Exception as exc:
            logger.error(f"[HybridEngine] Failed to start Tier {tier}: {exc}")
            return False

    async def stop_tier(self, tier: int) -> None:
        """Explicitly close a specific tier to free resources before escalation."""
        agent_map = {
            0: self._tier0, 1: self._tier1, 2: self._tier2,
            3: self._tier3, 4: self._tier4, 5: self._tier5,
        }
        agent = agent_map.get(tier)
        if agent:
            try:
                await agent.close()
                logger.info(f"[HybridEngine] 🛑 Tier {tier} explicitly CLOSED to free resources.")
            except Exception as exc:
                logger.warning(f"[HybridEngine] Tier {tier} close error: {exc}")

        if tier == 0:   self._tier0 = None
        elif tier == 1: self._tier1 = None
        elif tier == 2: self._tier2 = None
        elif tier == 3: self._tier3 = None
        elif tier == 4: self._tier4 = None
        elif tier == 5: self._tier5 = None

        # 🧹 PROACTIVE CLEANUP
        try:
            from common.disk_cleanup import check_and_cleanup
            check_and_cleanup(threshold_pct=90)
        except: pass

    async def stop_all(self) -> None:
        for tier in [0, 1, 2, 3, 4, 5]:
            await self.stop_tier(tier)

    async def close(self) -> None:
        await self.stop_all()

    async def rotate_proxy(self):
        """Forward proxy rotation to the active agent."""
        agent_map = {0: self._tier0, 1: self._tier1, 2: self._tier2, 3: self._tier3}
        agent = agent_map.get(self._current_tier)
        if agent and hasattr(agent, "rotate_proxy"):
            await agent.rotate_proxy()

    # ── Main orchestration & Delegation ───────────────────────────────────

    async def _execute_with_waterfall(self, method_name: str, *args, **kwargs) -> Any:
        """
        Executes a method on the active tier. If it fails (returns None or raises),
        closes the active tier and escalates to the next one.

        Adaptive Circuit Breaker (Bug #2 fix):
          - Tracks consecutive total failures across all tiers.
          - After _CB_THRESHOLD failures → opens circuit for _CB_PAUSE_SEC seconds.
          - A SUCCESS anywhere in the waterfall resets the failure counter.
          - Rationale: if the IP is banned by Google, retrying different engines
            is pointless — they ALL share the same IP.
        """
        # ── 0. DISK SPACE GUARD (Bug #5 — proactive auto-cleanup) ────────────
        try:
            from common.disk_cleanup import check_and_cleanup
            check_and_cleanup(threshold_pct=85)
        except Exception:
            pass  # Disk cleanup is best-effort — never block execution

        # ── 1. CIRCUIT BREAKER CHECK ──────────────────────────────────────────
        if self._circuit_breaker_open:
            if time.time() < self._circuit_breaker_until:
                remaining = int(self._circuit_breaker_until - time.time())
                logger.warning(
                    f"[HybridEngine] ⚡ Circuit breaker OPEN — "
                    f"🛑 IP likely banned. Skipping for {remaining}s."
                )
                return None
            else:
                # Cooling period over — reset and try again
                self._circuit_breaker_open = False
                self._consecutive_failures = 0
                logger.info("[HybridEngine] ⚡ Circuit breaker CLOSED — resuming operations.")

        # ── 2. SMART TIER SELECTION ───────────────────────────────────────────
        # If we have a 'last_successful_tier' that is still alive, try it FIRST.
        # This is CRITICAL for search -> extraction continuity.
        
        # PERFORMANCE_MODE: "simple" caps at Tier 2 (SeleniumBase + Patchright)
        if getattr(config, "PERFORMANCE_MODE", "full") == "simple":
            max_tier = 2
        else:
            max_tier = 5 if config.CAMOUFOX_ENABLED else 4
            
        # Safety: max_tier should never be lower than the starting tier
        max_tier = max(max_tier, config.HYBRID_DEFAULT_TIER)
            
        tier_sequence = list(range(config.HYBRID_DEFAULT_TIER, max_tier + 1))

        # If legacy Selenium is enabled, prepend it as Tier 0
        if getattr(config, "SELENIUM_ENABLED", False):
            tier_sequence.insert(0, 0)

        if self.last_successful_tier_used and self.last_successful_tier_used in tier_sequence:
            # Move it to the front of the list
            tier_sequence.remove(self.last_successful_tier_used)
            tier_sequence.insert(0, self.last_successful_tier_used)

        logger.debug(
            f"[HybridEngine] Waterfall sequence: {tier_sequence} "
            f"for '{method_name}' "
            f"(consecutive_failures={self._consecutive_failures})"
        )

        for tier in tier_sequence:
            self._current_tier = tier
            started = await self.start_tier(tier)
            if not started:
                logger.info(f"    ⚠️  [HybridEngine] Tier {tier} unavailable. Falling back...")
                if tier == 4:
                    break
                continue

            agent_map = {
                0: self._tier0, 1: self._tier1, 2: self._tier2,
                3: self._tier3, 4: self._tier4, 5: self._tier5,
            }
            agent = agent_map[tier]

            # ── 2.1 RE-NAVIGATION CATCH-UP ───────────────────────────────────
            # If we just started a NEW tier (not Tier 1 or the sticky one), 
            # and we have a last_target_url, we must navigate to it before 
            # calling an extraction method.
            if tier != tier_sequence[0] and self._last_target_url and method_name != "goto_url":
                if "search" not in method_name and method_name == "extract_universal_data":
                    if hasattr(agent, "goto_url"):
                        logger.info(f"[HybridEngine] 🌐 Catching up Tier {tier} to URL: {self._last_target_url}")
                        await getattr(agent, "goto_url")(self._last_target_url)
                    else:
                        logger.debug(f"[HybridEngine] Tier {tier} lacks goto_url; skipping catch-up.")

            method = getattr(agent, method_name, None)

            if not method:
                logger.warning(
                    f"[HybridEngine] Tier {tier} does not support '{method_name}'. Escalating..."
                )
                await self.stop_tier(tier)
                continue

            worker_icon = "👷" if self.worker_id else "🤖"
            logger.info(f"    {worker_icon} [Tier {tier}] Executing: {method_name}...")

            t0 = time.perf_counter()
            self._stats[tier]["attempts"] += 1

            try:
                # ── 2.2 THE SAFETY NET: TIMEOUT GUARD (P0 FIX) ────────────
                # Prevents a single hung browser from blocking the whole agent loop.
                try:
                    result = await asyncio.wait_for(method(*args, **kwargs), timeout=90.0)
                except asyncio.TimeoutError:
                    logger.error(f"🛑 [HybridEngine] Tier {tier} HANG/TIMEOUT in '{method_name}' after 90s.")
                    await self.stop_tier(tier) # KILL IMMEDIATELY
                    continue # Try next tier
                
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._stats[tier]["total_ms"] += elapsed_ms

                if result:
                    self._stats[tier]["successes"] += 1
                    self._consecutive_failures = 0
                    self.last_successful_tier_used = tier
                    
                    # 📈 Persistent Telemetry: SUCCESS
                    get_telemetry().record(
                        engine_name=self._TIER_NAMES.get(tier, f"Tier {tier}"),
                        row_index=self.current_row_index,
                        status="SUCCESS",
                        latency_sec=elapsed_ms / 1000.0,
                        method_name=method_name
                    )

                    # Track last URL logic...
                    if method_name in ["goto_url", "submit_google_search", "search_google_ai_mode"]:
                        try:
                            # Tiers 0 & 1 use Selenium-style _driver
                            if tier in [0, 1] and hasattr(agent, "_driver") and agent._driver:
                                self._last_target_url = await asyncio.to_thread(
                                    lambda: agent._driver.current_url
                                )
                            # Tiers 2, 3, 5 use Playwright-style page
                            elif tier in [2, 3, 5] and hasattr(agent, "page") and agent.page:
                                self._last_target_url = agent.page.url
                        except: pass
                    
                    # 📈 Prometheus Metric: SUCCESS
                    SCRAPING_RESULTS.labels(tier=str(tier), scrap_method=method_name, status="SUCCESS").inc()
                    
                    return result

                # 📈 Prometheus Metric: EMPTY
                SCRAPING_RESULTS.labels(tier=str(tier), scrap_method=method_name, status="EMPTY").inc()
                
                logger.warning(
                    f"[HybridEngine] Tier {tier} method '{method_name}' returned empty. Escalating..."
                )
                # 📈 Persistent Telemetry: EMPTY
                get_telemetry().record(
                    engine_name=self._TIER_NAMES.get(tier, f"Tier {tier}"),
                    row_index=self.current_row_index,
                    status="EMPTY",
                    latency_sec=elapsed_ms / 1000.0,
                    method_name=method_name
                )
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._stats[tier]["total_ms"] += elapsed_ms
                
                # 📈 Prometheus Metric: FAILURE
                SCRAPING_RESULTS.labels(tier=str(tier), scrap_method=method_name, status="FAILURE").inc()
                
                # 📈 Persistent Telemetry: FAILURE
                reason = "exception"
                exc_str = str(exc).lower()
                if "captcha" in exc_str or "waf" in exc_str: reason = "captcha_waf"
                elif "ip_ban" in exc_str or "forbidden" in exc_str: reason = "ip_ban"
                
                get_telemetry().record(
                    engine_name=self._TIER_NAMES.get(tier, f"Tier {tier}"),
                    row_index=self.current_row_index,
                    status="FAILURE",
                    latency_sec=elapsed_ms / 1000.0,
                    interruption_reason=reason,
                    method_name=method_name
                )

                logger.error(f"[HybridEngine] Tier {tier} exception in '{method_name}': {exc}")

            # Waterfall Escalate - KILL CURRENT TIER FIRST
            await self.stop_tier(tier)
            
            # Cool-down between tiers to let WAF sessions partially reset
            logger.info(f"[HybridEngine] 🕒 Cool-down delay: 5s...")
            await asyncio.sleep(5)

            self._current_tier = min(tier + 1, max_tier)

        # ── 3. ALL TIERS EXHAUSTED — update circuit breaker ──────────────────
        self._current_tier = config.HYBRID_DEFAULT_TIER
        self._consecutive_failures += 1

        alert(
            "CRITICAL",
            "HybridEngine: all tiers exhausted during operation",
            {"method": method_name, "consecutive_failures": self._consecutive_failures},
        )

        # Open circuit breaker if failure threshold reached
        if self._consecutive_failures >= self._CB_THRESHOLD:
            self._circuit_breaker_open = True
            self._circuit_breaker_until = time.time() + self._CB_PAUSE_SEC
            alert(
                "CRITICAL",
                f"Circuit Breaker OPENED — IP likely rate-limited by Google. "
                f"Pausing all requests for {self._CB_PAUSE_SEC}s.",
                {
                    "failures": self._consecutive_failures,
                    "resume_in_seconds": self._CB_PAUSE_SEC,
                },
            )
            # Attempt proxy rotation if available
            # Attempt proxy rotation via engine's logic
            try:
                await self.rotate_proxy()
                logger.info("[HybridEngine] ♻️ Proxy rotation requested after circuit breaker opened.")
            except Exception as proxy_err:
                logger.warning(f"[HybridEngine] Proxy rotation failed: {proxy_err}")

        return None

    # ── Delegated Browser Methods ───────────────────────────────────────────
    # These act as drop-in replacements for PatchrightAgent methods.
    
    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        return await self._execute_with_waterfall("search_google_ai_mode", prompt)

    async def submit_google_search(self, query: str) -> bool:
        return await self._execute_with_waterfall("submit_google_search", query)
        
    async def extract_universal_data(self) -> dict:
        return await self._execute_with_waterfall("extract_universal_data")

    async def search_google_ai(self, query: str) -> Optional[str]:
        return await self._execute_with_waterfall("search_google_ai", query)

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
        return await self._execute_with_waterfall("search_gemini_ai", prompt)

    async def crawl_website(self, url: str) -> Optional[str]:
        return await self._execute_with_waterfall("crawl_website", url)

    # ── Diagnostics ────────────────────────────────────────────────────────

    def get_engine_stats(self) -> Dict[int, Dict[str, Any]]:
        result = {}
        for tier, data in self._stats.items():
            att = data["attempts"]
            suc = data["successes"]
            ms  = data["total_ms"]
            result[tier] = {
                "attempts":     att,
                "successes":    suc,
                "avg_ms":       round(ms / att) if att else 0,
                "success_rate": round(suc / att * 100, 1) if att else 0.0,
            }
        return result

    def print_engine_report(self) -> None:
        tier_names = {
            0: "SeleniumUCD 🟧",
            1: "SBase-UC   ⭐",
            2: "Patchright 🟦",
            3: "Nodriver   🟢",
            4: "Crawl4AI   🟡",
            5: "Camoufox 🦊 ",
        }
        print("\n" + "═" * 68)
        print("📊  Hybrid Engine Performance Report (6-Tier, SeleniumBase=Tier 1)")
        print("═" * 68)
        for tier, data in self.get_engine_stats().items():
            name = tier_names.get(tier, f"Tier {tier}")
            bar_filled = int(data["success_rate"] / 5)  # 20 chars = 100%
            bar = ("█" * bar_filled).ljust(20)
            print(
                f"  Tier {tier} [{name:14s}] [{bar}] "
                f"{data['successes']:>3}/{data['attempts']:<3} "
                f"({data['success_rate']:5.1f}%) | "
                f"avg {data['avg_ms']:>5}ms"
            )
        cb_status = "OPEN 🔴" if self._circuit_breaker_open else "CLOSED 🟢"
        print(f"  Circuit Breaker: {cb_status} | "
              f"Consecutive failures: {self._consecutive_failures}/{self._CB_THRESHOLD}")
        print("═" * 68 + "\n")
