from __future__ import annotations

"""
╔════════════════════════════════════════════════════════════════════════╗
║  browser/hybrid_engine.py                                              ║
║                                                                        ║
║  Central routing brain — selects the right scraping tier based on      ║
║  the target URL's protection level, then escalates on failure.         ║
║                                                                        ║
║  Decision matrix (10-Tier Waterfall — docs/AGENTS.md blueprint):       ║
║  ┌──────┬───────────────────────────────────────────────────────────┐  ║
║  │ Tier │ Agent                                                     │  ║
║  ├──────┼───────────────────────────────────────────────────────────┤  ║
║  │ 2    │ SeleniumBase UC (Primary, Turnstile bypass)               │  ║
║  │ 3    │ Botasaurus (Profile rotation)                             │  ║
║  │ 4    │ CloakBrowser (Supreme Stealth, C++ level patches)         │  ║
║  │ 5    │ Nodriver (CDP Direct, Hard WAFs)                          │  ║
║  │ 6    │ Crawl4AI (E-commerce managed JS rendering)                │  ║
║  │ 7    │ Camoufox 🦊 (Firefox anti-detect, Chrome last resort)     │  ║
║  │ 8    │ Firecrawl (Premium Managed API)                           │  ║
║  │ 9    │ Jina Reader (High-speed Markdown conversion)              │  ║
║  │ 10   │ Crawlee (Industrial Playwright crawling)                  │  ║
║  │ 0    │ Legacy Selenium (Benchmark only)                          │  ║
║  └──────┴───────────────────────────────────────────────────────────┘  ║
║                                                                        ║
║  Escalation waterfall:                                                 ║
║    Tier 2 → Tier 3 → Tier 4 → Tier 5 → Tier 6 → Tier 7                 ║
║      → Tier 8 → Tier 9 → Tier 10                                       ║
║        → ALL FAIL: Circuit Breaker OPEN → pause 300s                   ║
╚════════════════════════════════════════════════════════════════════════╝
"""


import asyncio
import time
from typing import Optional, Dict, Any, List, TYPE_CHECKING

from core import config
from core.logger import get_logger, alert
from core.observability import SCRAPING_RESULTS
from common.metrics import get_telemetry

logger = get_logger(__name__)


from infra.browsers.network_probe import NetworkSpeedProbe
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
# TIER DEFINITIONS
# ─────────────────────────────────────────────────────────────────────────────

TIER_NAMES = {
    0: "selenium_legacy",
    # NOTE: Scrapy is NOT a waterfall tier — it's a post-discovery bonus step.
    # It activates inside search_google_ai_mode() when a website URL is found
    # but no phone number was returned by the browser tier.
    2: "seleniumbase",
    3: "botasaurus",
    4: "cloakbrowser",
    5: "nodriver",
    6: "crawl4ai",
    7: "camoufox",
    8: "firecrawl",
    9: "jina",
    10: "crawlee",
}


# ─────────────────────────────────────────────────────────────────────────────
# HYBRID ENGINE  (async context manager)
# ─────────────────────────────────────────────────────────────────────────────


class HybridAutomationEngine:
    """
    The main orchestrator. Manages all three tier agents as a pool
    and routes each task to the appropriate one.
    """

    # ── Configuration & Resource Locks ─────────────────────────────────────
    _CB_THRESHOLD = 3  # Consecutive failures before opening circuit
    _CB_PAUSE_SEC = 60  # 5 minutes pause — lets WAF cool down + proxy rotate
    _TIER_STARTUP_SEC = 120.0  # Max seconds to wait for any browser tier to start

    # Tier 5 (Camoufox/Firefox) is extremely heavy (~1 GB RAM).
    # We limit it to a single concurrent instance across ALL workers.
    _tier4_global_lock = asyncio.Lock()  # Originally named for Tier 4, reused for Tier 5

    def __init__(self, worker_id: int = 0):
        self._worker_id = worker_id
        from agents.base_agent import BaseBrowserAgent  # Local import to avoid circular dependency

        self._tier0: Optional[BaseBrowserAgent] = None  # SeleniumAgent      (Legacy/Benchmark)
        # Tier 1 slot removed — Scrapy is now a post-discovery bonus, not a waterfall tier.
        self._tier2: Optional[BaseBrowserAgent] = None  # SeleniumBaseAgent  (UC Driver) ⭐ PRIMARY
        self._tier3: Optional[BaseBrowserAgent] = None  # BotasaurusAgent    (Anti-detect)
        self._tier4: Optional[BaseBrowserAgent] = None  # CloakAgent         (Supreme Stealth)
        self._tier5: Optional[BaseBrowserAgent] = None  # NodriverAgent      (Chrome CDP)
        self._tier6: Optional[BaseBrowserAgent] = None  # Crawl4AIAgent      (Chrome managed)
        self._tier7: Optional[BaseBrowserAgent] = None  # CamoufoxAgent      (Firefox anti-detect)
        self._tier8: Optional[BaseBrowserAgent] = None  # FirecrawlAgent     (Premium managed)
        self._tier9: Optional[BaseBrowserAgent] = None  # JinaAgent          (High-speed Markdown)
        self._tier10: Optional[BaseBrowserAgent] = None  # CrawleeAgent       (Industrial crawler)

        # ── Circuit Breaker state ─────────────────────────────────────────────
        # Prevents infinite retry storms when ALL tiers fail due to IP banning.
        self._current_tier = config.HYBRID_DEFAULT_TIER
        self._last_successful_tier: Optional[int] = None
        self._circuit_breaker_open = False
        self._circuit_breaker_until = 0.0
        self._consecutive_failures = 0
        self._last_target_url: Optional[str] = None  # For re-navigation catch-up
        self._last_failure_reason: Optional[str] = (
            None  # "network"|"captcha_waf"|"code_bug"|"exception"|None
        )
        self.current_row_index: int = 0  # Track current row for telemetry
        self.last_successful_tier_used: Optional[int] = None  # For per-row export

        self._stats: Dict[Any, Dict[str, Any]] = {
            0: {"attempts": 0, "successes": 0, "total_ms": 0},
            # Scrapy bonus step tracked separately
            "scrapy_bonus": {"attempts": 0, "successes": 0, "total_ms": 0},
            2: {"attempts": 0, "successes": 0, "total_ms": 0},  # SeleniumBase
            3: {"attempts": 0, "successes": 0, "total_ms": 0},  # Botasaurus
            4: {"attempts": 0, "successes": 0, "total_ms": 0},  # Patchright
            5: {"attempts": 0, "successes": 0, "total_ms": 0},  # Nodriver
            6: {"attempts": 0, "successes": 0, "total_ms": 0},  # Crawl4AI
            7: {"attempts": 0, "successes": 0, "total_ms": 0},  # Camoufox
            8: {"attempts": 0, "successes": 0, "total_ms": 0},  # Firecrawl
            9: {"attempts": 0, "successes": 0, "total_ms": 0},  # Jina
            10: {"attempts": 0, "successes": 0, "total_ms": 0},  # Crawlee
        }

    @property
    def worker_id(self):
        return self._worker_id

    @property
    def firecrawl_agent(self):
        """Expose Tier 8 for direct access by specialized agents (e.g. phone_hunter)."""
        return self._tier8

    @property
    def jina_agent(self):
        """Expose Tier 9 for direct access (Jina Reader)."""
        return self._tier9

    @property
    def crawlee_agent(self):
        """Expose Tier 10 for direct access (Crawlee)."""
        return self._tier10

    # ── Context manager support ────────────────────────────────────────────

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        await self.stop_all()

    # ── Tier management ────────────────────────────────────────────────────

    async def start_tier(self, tier: int) -> bool:
        """Start a browser tier, failing fast after _TIER_STARTUP_SEC seconds."""
        try:
            return await asyncio.wait_for(
                self._start_tier_inner(tier),
                timeout=self._TIER_STARTUP_SEC,
            )
        except asyncio.TimeoutError:
            logger.error(
                f"[HybridEngine] ⏰ Tier {tier} startup TIMED OUT ({self._TIER_STARTUP_SEC:.0f}s) — "
                "Chrome/chromedriver version mismatch or resource starvation. Skipping tier."
            )
            await self.stop_tier(tier)
            return False

    async def _start_tier_inner(self, tier: int) -> bool:
        """Raw tier startup logic (no timeout guard — called by start_tier)."""
        try:
            # 1. Check if existing agent is alive
            agent_map = {
                0: self._tier0,
                2: self._tier2,
                3: self._tier3,
                4: self._tier4,
                5: self._tier5,
                6: self._tier6,
                7: self._tier7,
                8: self._tier8,
                9: self._tier9,
                10: self._tier10,
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
                logger.info(
                    f"[HybridEngine] ✅ Tier 0 (SeleniumUCD/Legacy) started for worker {self.worker_id}."
                )

            # ── Tier 2: SeleniumBase UC Driver (PRIMARY ⭐) ────────────────
            elif tier == 2 and not self._tier2:
                if not getattr(config, "SELENIUMBASE_ENABLED", True):
                    logger.warning(
                        "[HybridEngine] Tier 2 (SeleniumBase) is DISABLED in config. Skipping."
                    )
                    return False
                from infra.browsers.seleniumbase_agent import SeleniumBaseAgent

                self._tier2 = SeleniumBaseAgent(worker_id=self._worker_id)
                await self._tier2.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 2 ⭐ (SeleniumBase UC) started for worker {self.worker_id}."
                )

            # ── Tier 3: BotasaurusAgent (Anti-detect) ─────────────────────────
            elif tier == 3 and not self._tier3:
                if not getattr(config, "BOTASAURUS_ENABLED", True):
                    logger.warning(
                        "[HybridEngine] Tier 3 (Botasaurus) is DISABLED in config. Skipping."
                    )
                    return False
                from infra.browsers.botasaurus_agent import BotasaurusAgent

                self._tier3 = BotasaurusAgent(worker_id=self._worker_id)
                await self._tier3.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 3 🦖 (Botasaurus) started for worker {self.worker_id}."
                )

            # ── Tier 4: CloakAgent (Supreme Stealth — C++ patched) ───────────
            elif tier == 4 and not self._tier4:
                from infra.browsers.cloak_agent import CloakAgent

                self._tier4 = CloakAgent(worker_id=self._worker_id)
                await self._tier4.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 4 (CloakBrowser/Supreme) started for worker {self.worker_id}."
                )

            # ── Tier 5: NodriverAgent (Chrome CDP — no chromedriver) ──────
            elif tier == 5 and not self._tier5:
                from infra.browsers.nodriver_agent import NodriverAgent

                self._tier5 = NodriverAgent(worker_id=self._worker_id)
                await self._tier5.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 5 (Nodriver/Chrome CDP) started for worker {self.worker_id}."
                )

            # ── Tier 6: Crawl4AIAgent (Chrome managed) ────────────────────
            elif tier == 6 and not self._tier6:
                from infra.browsers.crawl4ai_agent import Crawl4AIAgent

                self._tier6 = Crawl4AIAgent(worker_id=self._worker_id)
                await self._tier6.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 6 (Crawl4AI/Chrome) started for worker {self.worker_id}."
                )

            # ── Tier 7: CamoufoxAgent (Firefox anti-detect — last resort) ─
            elif tier == 7 and not self._tier7:
                if not config.CAMOUFOX_ENABLED:
                    logger.warning(
                        "[HybridEngine] Tier 7 (Camoufox) is DISABLED in config. Skipping."
                    )
                    return False
                async with self._tier4_global_lock:
                    from infra.browsers.camoufox_agent import CamoufoxAgent

                    self._tier7 = CamoufoxAgent(worker_id=self._worker_id)
                    await self._tier7.start()
                    logger.info(
                        f"[HybridEngine] ✅ Tier 7 🦊 (Camoufox) started for worker {self.worker_id} (Global Lock Acquired)."
                    )

            # ── Tier 8: FirecrawlAgent (Premium managed) ───────────────────
            elif tier == 8 and not self._tier8:
                if not config.FIRECRAWL_ENABLED:
                    logger.warning(
                        "[HybridEngine] Tier 8 (Firecrawl) is DISABLED in config. Skipping."
                    )
                    return False
                from infra.browsers.firecrawl_agent import FirecrawlAgent

                self._tier8 = FirecrawlAgent(worker_id=self._worker_id)
                await self._tier8.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 8 (Firecrawl) started for worker {self.worker_id}."
                )

            # ── Tier 9: JinaAgent (High-speed Markdown Reader) ────────────
            elif tier == 9 and not self._tier9:
                if not config.JINA_ENABLED:
                    logger.warning("[HybridEngine] Tier 9 (Jina) is DISABLED in config. Skipping.")
                    return False
                from infra.browsers.jina_agent import JinaAgent

                self._tier9 = JinaAgent(worker_id=self._worker_id)
                await self._tier9.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 9 (Jina Reader) started for worker {self.worker_id}."
                )

            # ── Tier 10: CrawleeAgent (Industrial Crawler) ─────────────────
            elif tier == 10 and not self._tier10:
                if not config.CRAWLEE_ENABLED:
                    logger.warning(
                        "[HybridEngine] Tier 10 (Crawlee) is DISABLED in config. Skipping."
                    )
                    return False
                from infra.browsers.crawlee_agent import CrawleeAgent

                self._tier10 = CrawleeAgent(worker_id=self._worker_id)
                await self._tier10.start()
                logger.info(
                    f"[HybridEngine] ✅ Tier 10 (Crawlee) started for worker {self.worker_id}."
                )

            return True
        except ImportError as ie:
            logger.warning(
                f"  ⏭️ [HybridEngine] Tier {tier} is NOT INSTALLED or DISABLED! Skip to next available tier."
            )
            pkg_name = getattr(ie, "name", None) or "required dependencies"
            logger.warning(f"     Run: pip install {pkg_name}")
            return False
        except Exception as exc:
            logger.warning(f"[HybridEngine] Failed to start Tier {tier}: {exc}")
            return False

    async def stop_tier(self, tier: int) -> None:
        """Explicitly close a specific tier to free resources before escalation."""
        agent_map = {
            0: self._tier0,
            2: self._tier2,
            3: self._tier3,
            4: self._tier4,
            5: self._tier5,
            6: self._tier6,
            7: self._tier7,
            8: self._tier8,
            9: self._tier9,
            10: self._tier10,
        }
        agent = agent_map.get(tier)
        if agent:
            try:
                await agent.close()
                logger.info(f"[HybridEngine] 🛑 Tier {tier} explicitly CLOSED to free resources.")
            except Exception as exc:
                logger.warning(f"[HybridEngine] Tier {tier} close error: {exc}")

        if tier == 0:
            self._tier0 = None
        elif tier == 2:
            self._tier2 = None
        elif tier == 3:
            self._tier3 = None
        elif tier == 4:
            self._tier4 = None
        elif tier == 5:
            self._tier5 = None
        elif tier == 6:
            self._tier6 = None
        elif tier == 7:
            self._tier7 = None
        elif tier == 8:
            self._tier8 = None
        elif tier == 9:
            self._tier9 = None
        elif tier == 10:
            self._tier10 = None

        # 🧹 PROACTIVE CLEANUP
        try:
            from common.disk_cleanup import check_and_cleanup

            check_and_cleanup(threshold_pct=90)
        except Exception:
            pass

    async def stop_all(self) -> None:
        for tier in [0, 2, 3, 4, 5, 6, 7, 8, 9, 10]:
            await self.stop_tier(tier)

    async def close(self) -> None:
        await self.stop_all()

    async def rotate_proxy(self):
        """Forward proxy rotation to the currently active agent."""
        agent_map = {
            0: self._tier0,
            2: self._tier2,
            3: self._tier3,
            4: self._tier4,
            5: self._tier5,
            6: self._tier6,
            7: self._tier7,
            8: self._tier8,
            9: self._tier9,
            10: self._tier10,
        }
        agent = agent_map.get(self._current_tier)
        if agent and hasattr(agent, "rotate_proxy"):
            await agent.rotate_proxy()

    # ── Main orchestration & Delegation ───────────────────────────────────
    # Every public browser method (search, crawl, etc.) funnels through here.
    # The waterfall tries tiers in ascending order of sophistication until
    # one succeeds or the circuit breaker trips.

    async def _execute_with_waterfall(self, method_name: str, *args, **kwargs) -> Any:
        """
        Execute `method_name` on the current tier; escalate on failure.

        Args:
            method_name : Browser method to call (e.g. "search_google_ai_mode")
            use_browser : bool, optional. If True, bypass Tier 1 (Scrapy) and go straight to headless.
            *args, **kwargs : Passed verbatim to that method

        Returns:
            Whatever the method returns, or None if all tiers fail.

        Circuit Breaker rationale:
          All tiers share the same outbound IP.  If Google bans it, every
          tier will fail.  After _CB_THRESHOLD consecutive failures we pause
          for _CB_PAUSE_SEC seconds to let the WAF cool down.
        """
        # ── 0. PER-CALL STATE RESET ───────────────────────────────────────────
        # Reset failure reason + soft-retry flags so previous-row state never
        # bleeds into this call.
        self._last_failure_reason = None
        # Clear any soft-retry flags from the previous row (keyed as
        # "_soft_retry_{tier}_{method_name}" on self)
        for _attr in [k for k in self.__dict__ if k.startswith("_soft_retry_")]:
            delattr(self, _attr)

        # Strip internal parameters that should not propagate to tier methods
        kwargs.pop("row", None)
        
        has_network_failure = False

        # ── 0.1 DISK SPACE GUARD (Bug #5 — proactive auto-cleanup) ──────────
        try:
            from common.disk_cleanup import check_and_cleanup

            check_and_cleanup(threshold_pct=85)
        except Exception:
            pass  # Disk cleanup is best-effort — never block execution

        # ── 0.5 PROMPT VALIDATION ─────────────────────────────────────────────
        if "search" in method_name:
            prompt_val = args[0] if len(args) > 0 else kwargs.get("prompt", "")
            if not prompt_val or not str(prompt_val).strip():
                logger.warning(f"[HybridEngine] Empty prompt provided for {method_name}. Aborting.")
                return None

        # ── 1. CIRCUIT BREAKER CHECK ──────────────────────────────────────────
        if self._circuit_breaker_open:
            if time.time() < self._circuit_breaker_until:
                remaining = int(self._circuit_breaker_until - time.time())
                logger.warning(
                    f"[HybridEngine] ⚡ Circuit breaker OPEN — "
                    f"🛑 IP likely banned. Pausing execution for {remaining}s..."
                )
                await asyncio.sleep(remaining)
                # After sleeping, reset and try again instead of skipping
                self._circuit_breaker_open = False
                self._consecutive_failures = 0
                logger.info("[HybridEngine] ⚡ Circuit breaker COOLDOWN finished — resuming.")
            else:
                # Cooling period over — reset and try again
                self._circuit_breaker_open = False
                self._consecutive_failures = 0
                logger.info("[HybridEngine] ⚡ Circuit breaker CLOSED — resuming operations.")

        # ── 2. SMART TIER SELECTION ───────────────────────────────────────────
        # If we have a 'last_successful_tier' that is still alive, try it FIRST.
        # This is CRITICAL for search -> extraction continuity.

        # PERFORMANCE_MODE escalation caps
        p_mode = getattr(config, "PERFORMANCE_MODE", "full")

        # ── 2.1 NETWORK SPEED PROBE (adaptive timeout guard) ───────────────────
        # Run a lightweight probe before each batch to calibrate timeout multiplier.
        # Bad networks cause aggressive timeouts which amplify ban risk.
        net_score, net_latency = await NetworkSpeedProbe.probe()
        if net_score == "bad":
            logger.warning(
                f"[HybridEngine] 🌐 Slow network detected (latency={net_latency:.0f}ms) — "
                f"extending all timeouts x{NetworkSpeedProbe.get_timeout_multiplier():.1f}"
            )
            # Extra backoff before starting: let the connection settle
            await asyncio.sleep(2)

        # Browser waterfall: starts at Tier 2 (SeleniumBase).
        # Scrapy is NOT in this sequence — it fires as a bonus inside search_google_ai_mode.
        if p_mode == "simple":
            tier_sequence = [2, 3]  # SeleniumBase + Botasaurus
        elif p_mode == "stealth":
            tier_sequence = [2, 5]  # SeleniumBase + Nodriver
        elif p_mode == "balanced":
            tier_sequence = [2, 3, 4]  # SeleniumBase + Botasaurus + CloakBrowser
        else:
            # "full" mode or custom Golden Path sequence
            tier_sequence = [2, 5, 4, 6]

            # Additional tiers if explicitly configured to run beyond the Golden Path
            if config.CAMOUFOX_ENABLED:
                tier_sequence.append(7)
            if config.FIRECRAWL_ENABLED:
                tier_sequence.append(8)
            if config.CRAWLEE_ENABLED:
                tier_sequence.append(10)

        # Apply strict global cap from config
        tier_sequence = [t for t in tier_sequence if t <= config.MAX_WATERFALL_TIER]

        max_tier = max(tier_sequence) if tier_sequence else 2

        # If legacy Selenium is enabled, prepend it as Tier 0
        if getattr(config, "SELENIUM_ENABLED", False):
            tier_sequence.insert(0, 0)

        # use_browser kwarg kept for backward compat but no longer skips Scrapy
        kwargs.pop("use_browser", None)

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
            # Always reset per-tier failure accumulation to avoid runaway loops
            # across tiers/rows.
            self._last_failure_reason = None
            self._current_tier = tier
            started = await self.start_tier(tier)
            if not started:
                logger.info(f"    ⚠️  [HybridEngine] Tier {tier} unavailable. Falling back...")
                if tier == 4:
                    break
                continue

            agent_map = {
                0: self._tier0,
                2: self._tier2,
                3: self._tier3,
                4: self._tier4,
                5: self._tier5,
                6: self._tier6,
                7: self._tier7,
                8: self._tier8,
                9: self._tier9,
                10: self._tier10,
            }
            agent = agent_map[tier]

            # ── 2.1 RE-NAVIGATION CATCH-UP ───────────────────────────────────
            # If we just started a NEW tier (not Tier 1 or the sticky one),
            # and we have a last_target_url, we must navigate to it before
            # calling an extraction method.
            if tier != tier_sequence[0] and self._last_target_url and method_name != "goto_url":
                if "search" not in method_name and method_name == "extract_universal_data":
                    if hasattr(agent, "goto_url"):
                        logger.info(
                            f"[HybridEngine] 🌐 Catching up Tier {tier} to URL: {self._last_target_url}"
                        )
                        await getattr(agent, "goto_url")(self._last_target_url)
                    else:
                        logger.debug(
                            f"[HybridEngine] Tier {tier} lacks goto_url; skipping catch-up."
                        )

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
                # ── 2.2 ADAPTIVE TIMEOUT GUARD ───────────────────────────────
                # AI-mode searches can legitimately take 20-60s to stream.
                # A flat 15s timeout kills valid results and wastes tier escalations.
                # Method-specific budgets prevent hung browsers from blocking.
                _TIMEOUT_MAP = {
                    "search_google_ai_mode": 90.0,  # AI Overview streams slowly
                    "search_google_ai": 90.0,  # Legacy AI search alias
                    "search_google_ai_interactive": 90.0,  # Human-interactive flow
                    "search_gemini_ai": 60.0,  # Gemini chat response
                    "crawl_website": 45.0,  # Deep-crawl a single page
                    "submit_google_search": 30.0,  # Type + Enter + wait
                    "goto_url": 20.0,  # Simple navigation
                    "extract_universal_data": 15.0,  # Fast DOM extraction
                    "get_page_source": 10.0,  # Instant snapshot
                }
                _timeout = _TIMEOUT_MAP.get(method_name, 30.0) * getattr(
                    config, "NETWORK_SPEED_MULTIPLIER", 1.0
                ) * NetworkSpeedProbe.get_timeout_multiplier()
                try:
                    result = await asyncio.wait_for(method(*args, **kwargs), timeout=_timeout)
                except asyncio.TimeoutError:
                    logger.warning(
                        f"⏳ [HybridEngine] Tier {tier} TIMEOUT in '{method_name}' "
                        f"after {_timeout:.0f}s. Escalating..."
                    )
                    await self.stop_tier(tier)  # Kill hung browser immediately
                    continue

                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._stats[tier]["total_ms"] += elapsed_ms

                if result:
                    self._stats[tier]["successes"] += 1
                    self._consecutive_failures = 0
                    self.last_successful_tier_used = tier

                    # 📈 Persistent Telemetry: SUCCESS
                    get_telemetry().record(
                        engine_name=TIER_NAMES.get(tier, f"Tier {tier}"),
                        row_index=self.current_row_index,
                        status="SUCCESS",
                        latency_sec=elapsed_ms / 1000.0,
                        method_name=method_name,
                    )
                    get_telemetry().save()  # Persist real-time metrics

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
                        except Exception:
                            pass

                    # 📈 Prometheus Metric: SUCCESS
                    SCRAPING_RESULTS.labels(
                        tier=str(tier), scrap_method=method_name, status="SUCCESS"
                    ).inc()

                    return result

                # 📈 Prometheus Metric: EMPTY
                SCRAPING_RESULTS.labels(
                    tier=str(tier), scrap_method=method_name, status="EMPTY"
                ).inc()

                # ── SOFT-RETRY (Issue #3 fix) ─────────────────────────────────
                # On a clean empty result (no exception, no block signal), do ONE
                # soft-retry with a brief pause on the SAME tier before escalating.
                # Rationale: Google AI Mode sometimes streams results late; killing
                # the tier immediately and restarting a new browser amplifies ban risk.
                # Only applies to AI-search methods — fast extract methods escalate now.
                _is_search_method = "search" in method_name
                _soft_retry_key = f"_soft_retry_{tier}_{method_name}"
                _already_retried = getattr(self, _soft_retry_key, False)

                if _is_search_method and not _already_retried:
                    setattr(self, _soft_retry_key, True)
                    logger.info(
                        f"[HybridEngine] 🔄 Tier {tier} '{method_name}' empty — "
                        f"soft-retry in 3s (same tier, no browser restart)..."
                    )
                    await asyncio.sleep(3)
                    # Reset t0 for accurate per-retry latency
                    t0 = time.perf_counter()
                    # Don't escalate — go back to the top of the loop for the same tier
                    continue
                else:
                    # Soft-retry already used or non-search method → escalate
                    if hasattr(self, _soft_retry_key):
                        delattr(self, _soft_retry_key)
                    logger.warning(
                        f"[HybridEngine] Tier {tier} method '{method_name}' returned empty "
                        f"{'after soft-retry' if _already_retried else ''}. Escalating..."
                    )

                # 📈 Persistent Telemetry: EMPTY
                get_telemetry().record(
                    engine_name=TIER_NAMES.get(tier, f"Tier {tier}"),
                    row_index=self.current_row_index,
                    status="EMPTY",
                    latency_sec=elapsed_ms / 1000.0,
                    method_name=method_name,
                )
                get_telemetry().save()  # Persist real-time metrics
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._stats[tier]["total_ms"] += elapsed_ms

                # Diagnostic: confirm which agent/method actually raised.
                try:
                    agent_name = type(agent).__name__ if agent is not None else "<agent=None>"
                    agent_mod = type(agent).__module__ if agent is not None else ""
                    method_obj = getattr(agent, method_name, None) if agent is not None else None
                    import inspect

                    sig = None
                    if method_obj is not None:
                        try:
                            sig = str(inspect.signature(method_obj))
                        except Exception:
                            sig = "<no-signature>"
                    logger.error(
                        f"[HybridEngine][Diag] tier={tier} method={method_name} "
                        f"agent={agent_name} ({agent_mod}) signature={sig} "
                        f"exc={type(exc).__name__}: {exc}"
                    )
                except Exception:
                    pass

                # ── FIX #4: Triage exceptions — code bugs vs network failures ──
                # Code-level errors (NameError, ImportError, TypeError, AttributeError)
                # indicate a BUG in the tier code, or a VALIDATION error, NOT an IP ban.
                # They must NOT increment _consecutive_failures or trigger the circuit
                # breaker, which would cause a 300s dead-sleep on every single row.
                _CODE_LEVEL_ERRORS = (
                    NameError,
                    ImportError,
                    TypeError,
                    AttributeError,
                    SyntaxError,
                    ValueError,
                    AssertionError,
                    NotImplementedError,
                )
                _is_code_error = isinstance(exc, _CODE_LEVEL_ERRORS)

                exc_str = str(exc).lower()
                # Network/WAF signals: treat as genuine failures worthy of CB
                # `agent` can be None in some exception paths; guard to avoid
                # "NoneType has no attribute is_block_response".
                if agent is None or not hasattr(agent, "is_block_response"):
                    _is_network_error = False
                else:
                    # FIX: pass str(exc) — some subclasses call content.lower() directly
                    # without a str() cast; passing the raw exception would raise
                    # AttributeError: 'XxxError' object has no attribute 'lower'.
                    _is_network_error = agent.is_block_response(str(exc))

                # Determine interruption reason for telemetry
                if _is_code_error:
                    reason = "code_bug"
                    logger.error(
                        f"[HybridEngine] 🐛 Tier {tier} CODE BUG in '{method_name}': "
                        f"{type(exc).__name__}: {exc}  "
                        f"(circuit breaker NOT penalized — this is a code error, not an IP ban)"
                    )
                elif "captcha" in exc_str or "waf" in exc_str:
                    reason = "captcha_waf"
                    has_network_failure = True
                    logger.error(
                        f"[HybridEngine] Tier {tier} CAPTCHA/WAF in '{method_name}': {exc}"
                    )
                elif _is_network_error:
                    reason = "network"
                    has_network_failure = True
                    logger.error(
                        f"[HybridEngine] Tier {tier} NETWORK error in '{method_name}': {exc}"
                    )
                else:
                    reason = "exception"
                    logger.error(f"[HybridEngine] Tier {tier} exception in '{method_name}': {exc}")

                self._last_failure_reason = reason

                # 📈 Prometheus Metric: FAILURE
                SCRAPING_RESULTS.labels(
                    tier=str(tier), scrap_method=method_name, status="FAILURE"
                ).inc()

                # 📈 Persistent Telemetry: FAILURE
                get_telemetry().record(
                    engine_name=TIER_NAMES.get(tier, f"Tier {tier}"),
                    row_index=self.current_row_index,
                    status="FAILURE",
                    latency_sec=elapsed_ms / 1000.0,
                    interruption_reason=reason,
                    method_name=method_name,
                )
                get_telemetry().save()  # Persist real-time metrics

                # Code bugs: fast escalate — no cool-down, no CB penalty
                if _is_code_error:
                    try:
                        await self.stop_tier(tier)
                    except Exception as stop_exc:
                        logger.warning(f"[HybridEngine] stop_tier({tier}) failed: {stop_exc}")
                    continue  # Skip the 8s cool-down below, escalate immediately

            # Waterfall Escalate - KILL CURRENT TIER FIRST
            try:
                await self.stop_tier(tier)
            except Exception as stop_exc:
                logger.warning(f"[HybridEngine] stop_tier({tier}) escalated cleanup failed: {stop_exc}")

            # ── Smart cool-down: only pause for genuine network/WAF failures ──
            # Empty results or code bugs do NOT need a WAF cooldown period.
            _last_reason = getattr(self, "_last_failure_reason", None)
            if _last_reason in ("network", "captcha_waf"):
                logger.info(
                    "[HybridEngine] 🕒 Network/WAF failure — cooling down 8s before next tier..."
                )
                await asyncio.sleep(3)
            else:
                logger.debug(
                    f"[HybridEngine] ⚡ Escalating immediately (reason={_last_reason or 'empty'})."
                )

            self._current_tier = min(tier + 1, max_tier)

        # ── 3. ALL TIERS EXHAUSTED — update circuit breaker ──────────────────
        # FIX #4: Only penalize the circuit breaker for genuine network/scraping
        # failures. If all tiers failed due to code bugs, log loudly but do NOT
        # open the circuit breaker (that would cause a 300s sleep per row).
        self._current_tier = config.HYBRID_DEFAULT_TIER

        # Determine if the exhaustion was caused by code bugs (no CB penalty)
        # We track this via the stats: if every failing tier had 0 latency or
        # the exception was code-level, we skip the CB increment.
        # Conservative approach: increment CB counter only for network-type runs.
        # (Code-bug tiers `continue` before reaching this point, so reaching
        # here means at least one genuine network-level attempt was made.)
        if has_network_failure or getattr(self, "_last_failure_reason", None) in ("network", "captcha_waf"):
            self._consecutive_failures += 1

        alert(
            "CRITICAL",
            "HybridEngine: all tiers exhausted during operation",
            {"method": method_name, "consecutive_failures": self._consecutive_failures},
        )

        # Open circuit breaker if failure threshold reached
        if self._consecutive_failures >= self._CB_THRESHOLD:
            # Reset per-row retry state so recursion/retry storms do not
            # cascade into the next row.
            self._last_failure_reason = None
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
            try:
                await self.rotate_proxy()
                logger.info(
                    "[HybridEngine] ♻️ Proxy rotation requested after circuit breaker opened."
                )
            except Exception as proxy_err:
                logger.warning(f"[HybridEngine] Proxy rotation failed: {proxy_err}")

        return None

    # ── Delegated Browser Methods ───────────────────────────────────────────
    # These act as drop-in replacements for PatchrightAgent methods.

    async def search_google_ai_mode(
        self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None
    ) -> Optional[str]:
        """
        AI Mode search via browser waterfall.

        Implements a dynamic engine-toggle strategy and an optional
        interactive human-like flow.
        """
        # ── 0. Validation & Pre-flight ─────────────────────────────────────────
        prompt = (prompt or "").strip()
        if not prompt:
            logger.warning("[HybridEngine] Refusing search with empty prompt.")
            return None

        # ── 0.5 Optional Interactive Flow (Human-Like) ──────────────────────────
        # If enabled in config, we bypass the direct URL generation and use
        # the high-stealth interactive flow (navigating to Google, typing).
        if getattr(config, "FORCE_HUMAN_INTERACTIVE", False):
            logger.info("[HybridEngine] 🎭 Forcing Interactive (Human-Like) search flow.")
            return await self.search_google_ai_interactive(prompt, ai_mode_url=None, row=row)

        primary_url = config.GOOGLE_AI_MODE_URL
        provider = "Google"

        logger.info(f"[HybridEngine] 🔄 Search provider: {provider} (row={self.current_row_index})")

        # ── Primary attempt ───────────────────────────────────────────────────
        result = await self._execute_with_waterfall(
            "search_google_ai_mode", prompt, ai_mode_url=primary_url, row=row
        )

        return result

    async def generate_human_noise(self) -> None:
        """
        Trigger a human-behaviour "session seasoning" visit on the currently
        active tier agent.  Delegates to the agent's own generate_human_noise()
        implementation so tier-specific browser APIs are used correctly.

        Called by the orchestrator every HUMAN_NOISE_INTERVAL rows.
        Silently no-ops if no suitable agent is available.
        """
        agent_map = {
            0: self._tier0,
            2: self._tier2,
            3: self._tier3,
            4: self._tier4,
            5: self._tier5,
            6: self._tier6,
            7: self._tier7,
            8: self._tier8,
            9: self._tier9,
            10: self._tier10,
        }
        # Prefer the current tier; walk backwards to find the closest live agent
        for tier in [self._current_tier] + list(reversed(sorted(agent_map.keys()))):
            agent = agent_map.get(tier)
            if agent and hasattr(agent, "generate_human_noise"):
                logger.info(
                    f"[HybridEngine] 🎭 Human Noise → Tier {tier} "
                    f"(worker={self._worker_id}, row={self.current_row_index})"
                )
                try:
                    await agent.generate_human_noise()
                except Exception as exc:
                    logger.debug(f"[HybridEngine] Noise generation error on Tier {tier}: {exc}")
                return
        logger.debug("[HybridEngine] No active agent found for human noise generation.")

    async def submit_google_search(self, prompt: str) -> bool:
        return await self._execute_with_waterfall("submit_google_search", prompt)

    async def extract_universal_data(self, use_browser: bool = False) -> dict:
        return await self._execute_with_waterfall("extract_universal_data", use_browser=use_browser)

    async def search_google_ai(
        self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None
    ) -> Optional[str]:
        """Legacy entry point — now delegates to search_google_ai_mode.

        Previously this dispatched _execute_with_waterfall("search_google_ai", ...)
        which caused a guaranteed NotImplementedError on EVERY tier agent (none of
        them implement the bare 'search_google_ai' method).  The waterfall would
        then fast-exhaust all 10 tiers, wasting time and logging misleading errors.

        FIX: Route directly to search_google_ai_mode, which is the canonically
        implemented method across all tier agents.
        """
        return await self.search_google_ai_mode(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_google_ai_interactive(
        self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None
    ) -> Optional[str]:
        """
        Interactive high-stealth search flow (Human-Like).
        Navigates to Google, types query, Enter, then clicks AI Mode.
        """
        return await self._execute_with_waterfall(
            "search_google_ai_interactive", prompt, ai_mode_url=ai_mode_url, row=row
        )

    async def search_gemini_ai(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Gemini AI search via browser waterfall.
        """
        return await self._execute_with_waterfall("search_gemini_ai", prompt, **kwargs)

    async def crawl_website(self, url: str, **kwargs) -> Optional[str]:
        """
        Deep-crawl a website via browser waterfall.
        """
        return await self._execute_with_waterfall("crawl_website", url, **kwargs)

    # ── Diagnostics ────────────────────────────────────────────────────────

    def get_engine_stats(self) -> Dict[int, Dict[str, Any]]:
        result = {}
        for tier, data in self._stats.items():
            att = data["attempts"]
            suc = data["successes"]
            ms = data["total_ms"]
            result[tier] = {
                "attempts": att,
                "successes": suc,
                "avg_ms": round(ms / att) if att else 0,
                "success_rate": round(suc / att * 100, 1) if att else 0.0,
            }
        return result

    def print_engine_report(self) -> None:
        # Friendly names for the console report
        FRIENDLY_NAMES = {
            0: "SeleniumUCD 🟧",
            1: "Scrapy 🕷️   ",
            2: "SBase-UC   ⭐",
            3: "Botasaurus 🦖",
            4: "CloakBrowser🕵️",
            5: "Nodriver   🟢",
            6: "Crawl4AI   🟡",
            7: "Camoufox 🦊 ",
            8: "Firecrawl 🔥 ",
            9: "Jina Reader⚡ ",
            10: "Crawlee 🛠️  ",
        }
        print("\n" + "═" * 68)
        print("📊  Hybrid Engine Performance Report (10-Tier, Scrapy=Tier 1)")
        print("═" * 68)
        for tier, data in self.get_engine_stats().items():
            name = FRIENDLY_NAMES.get(tier, f"Tier {tier}")
            bar_filled = int(data["success_rate"] / 5)  # 20 chars = 100%
            bar = ("█" * bar_filled).ljust(20)
            print(
                f"  Tier {tier} [{name:14s}] [{bar}] "
                f"{data['successes']:>3}/{data['attempts']:<3} "
                f"({data['success_rate']:5.1f}%) | "
                f"avg {data['avg_ms']:>5}ms"
            )
        cb_status = "OPEN 🔴" if self._circuit_breaker_open else "CLOSED 🟢"
        print(
            f"  Circuit Breaker: {cb_status} | "
            f"Consecutive failures: {self._consecutive_failures}/{self._CB_THRESHOLD}"
        )
        print("═" * 68 + "\n")
