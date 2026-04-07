"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/hybrid_engine.py                                                ║
║                                                                          ║
║  TASK 1 from GEMINI.md — Hybrid Automation Engine                        ║
║                                                                          ║
║  Central routing brain that selects the right scraping tier based on     ║
║  the target URL's protection level, then escalates on failure.           ║
║                                                                          ║
║  Decision matrix:                                                        ║
║  ┌──────────────────────────────────────┬────────────────────────────┐  ║
║  │ Target Type                          │ Agent                      │  ║
║  ├──────────────────────────────────────┼────────────────────────────┤  ║
║  │ Internal / no protection             │ Tier 1: PlaywrightAgent    │  ║
║  │ Cloudflare / LinkedIn / Facebook     │ Tier 2: NodriverAgent      │  ║
║  │ Amazon / Fnac / hardened e-commerce  │ Tier 3: Crawl4AIAgent      │  ║
║  └──────────────────────────────────────┴────────────────────────────┘  ║
║                                                                          ║
║  Escalation waterfall:                                                   ║
║    Tier 1 fails → Tier 2 → Tier 3 → CRITICAL alert + return None        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import time
from typing import Optional, Dict, Any, List

import config
from utils.logger import get_logger, alert

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

    Usage (as drop-in replacement):
        engine = HybridAutomationEngine(worker_id=1)
        # Automatically starts Tier 1, escalates to Tier 2 if it fails, closing Tier 1 first.
        content = await engine.search_google_ai_mode("Prompt")
    """

    def __init__(self, worker_id: int = 0):
        self._worker_id = worker_id
        self._tier1: Optional[object] = None   # PlaywrightAgent
        self._tier2: Optional[object] = None   # NodriverAgent
        self._tier3: Optional[object] = None   # Crawl4AIAgent
        self._current_tier = 1
        
        self._stats: Dict[int, Dict[str, Any]] = {
            1: {"attempts": 0, "successes": 0, "total_ms": 0},
            2: {"attempts": 0, "successes": 0, "total_ms": 0},
            3: {"attempts": 0, "successes": 0, "total_ms": 0},
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
            if tier == 1 and not self._tier1:
                from browser.playwright_agent import PlaywrightAgent
                self._tier1 = PlaywrightAgent(worker_id=self._worker_id)
                await self._tier1.start()
                logger.info(f"[HybridEngine] ✅ Tier 1 (Playwright) started for worker {self.worker_id}.")

            elif tier == 2 and not self._tier2:
                from browser.nodriver_agent import NodriverAgent
                self._tier2 = NodriverAgent()
                await self._tier2.start()
                logger.info(f"[HybridEngine] ✅ Tier 2 (Nodriver) started for worker {self.worker_id}.")

            elif tier == 3 and not self._tier3:
                from browser.crawl4ai_agent import Crawl4AIAgent
                self._tier3 = Crawl4AIAgent()
                await self._tier3.start()
                logger.info(f"[HybridEngine] ✅ Tier 3 (Crawl4AI) started for worker {self.worker_id}.")

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
        agent = {1: self._tier1, 2: self._tier2, 3: self._tier3}.get(tier)
        if agent:
            try:
                await agent.close()
                logger.info(f"[HybridEngine] 🛑 Tier {tier} explicitly CLOSED to free resources.")
            except Exception as exc:
                logger.warning(f"[HybridEngine] Tier {tier} close error: {exc}")
                
        if tier == 1: self._tier1 = None
        elif tier == 2: self._tier2 = None
        elif tier == 3: self._tier3 = None

    async def stop_all(self) -> None:
        for tier in [1, 2, 3]:
            await self.stop_tier(tier)
            
    async def close(self) -> None:
        await self.stop_all()

    async def rotate_proxy(self):
        """Forward proxy rotation to the active agent."""
        agent = {1: self._tier1, 2: self._tier2, 3: self._tier3}.get(self._current_tier)
        if agent and hasattr(agent, "rotate_proxy"):
            await agent.rotate_proxy()

    # ── Main orchestration & Delegation ───────────────────────────────────

    async def _execute_with_waterfall(self, method_name: str, *args, **kwargs) -> Any:
        """
        Executes a method on the active tier. If it fails (returns None or raises),
        closes the active tier and escalates to the next one.
        """
        # CRITICAL FIX: Always start new requests from Tier 1 (or default)
        # to prevent getting 'stuck' in a failed escalated tier from a previous row.
        self._current_tier = config.HYBRID_DEFAULT_TIER
        
        logger.debug(f"[HybridEngine] Starting waterfall from Tier {self._current_tier} for '{method_name}'")

        for tier in range(self._current_tier, 4):
            self._current_tier = tier
            started = await self.start_tier(tier)
            if not started:
                # If the tier can't start (missing dependency), continue to the next one
                # OR fallback to Tier 1 if we're not already there.
                logger.info(f"    ⚠️  [HybridEngine] Falling back from Tier {tier}...")
                if tier == 3: break
                continue

            agent = {1: self._tier1, 2: self._tier2, 3: self._tier3}[tier]
            method = getattr(agent, method_name, None)
            
            if not method:
                logger.warning(f"[HybridEngine] Tier {tier} does not support '{method_name}'. Escalating...")
                await self.stop_tier(tier)
                continue

            worker_icon = "👷" if self.worker_id else "🤖"
            logger.info(f"    {worker_icon} [Tier {tier}] Executing: {method_name}...")

            t0 = time.perf_counter()
            self._stats[tier]["attempts"] += 1

            try:
                result = await method(*args, **kwargs)
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._stats[tier]["total_ms"] += elapsed_ms

                if result:
                    self._stats[tier]["successes"] += 1
                    # Success! We don't reset _current_tier here yet, 
                    # but the next CALL to this engine will reset it.
                    return result
                
                logger.warning(f"[HybridEngine] Tier {tier} method '{method_name}' returned empty. Assuming failure.")
            except Exception as exc:
                elapsed_ms = int((time.perf_counter() - t0) * 1000)
                self._stats[tier]["total_ms"] += elapsed_ms
                logger.error(f"[HybridEngine] Tier {tier} exception in '{method_name}': {exc}")

            # Waterfall Escalate
            logger.warning(f"[HybridEngine] Escalating from Tier {tier} to Tier {tier+1}...")
            await self.stop_tier(tier) 
            
            # --- PERFORMANCE COOL-DOWN ---
            # Wait 5 seconds between tiers to let WAF sessions reset
            # and to clear the OS-level socket cache.
            logger.info(f"[HybridEngine] 🕒 Cool-down delay: 5s...")
            await asyncio.sleep(5)
            
            # Reset pointer for the absolute final failure/exit
            self._current_tier = tier + 1
        
        # Reset pointer for the next call
        self._current_tier = config.HYBRID_DEFAULT_TIER
        alert("CRITICAL", "HybridEngine: all tiers exhausted during operation", {"method": method_name})
        return None

    # ── Delegated Browser Methods ───────────────────────────────────────────
    # These act as drop-in replacements for PlaywrightAgent methods.
    
    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        return await self._execute_with_waterfall("search_google_ai_mode", prompt)

    async def submit_google_search(self, query: str) -> bool:
        return await self._execute_with_waterfall("submit_google_search", query)
        
    async def extract_knowledge_panel_phone(self) -> Optional[str]:
        return await self._execute_with_waterfall("extract_knowledge_panel_phone")

    async def search_google_ai(self, query: str) -> Optional[str]:
        return await self._execute_with_waterfall("search_google_ai", query)

    async def extract_aeo_data(self) -> Optional[List[Dict[str, Any]]]:
        return await self._execute_with_waterfall("extract_aeo_data")

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
        print("\n" + "═" * 60)
        print("📊  Hybrid Engine Performance Report")
        print("═" * 60)
        for tier, data in self.get_engine_stats().items():
            tier_name = {1: "Playwright", 2: "Nodriver", 3: "Crawl4AI"}[tier]
            print(
                f"  Tier {tier} [{tier_name:10s}] — "
                f"{data['successes']}/{data['attempts']} success "
                f"({data['success_rate']}%) | "
                f"avg {data['avg_ms']}ms"
            )
        print("═" * 60 + "\n")
