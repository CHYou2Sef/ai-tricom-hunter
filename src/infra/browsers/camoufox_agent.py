"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/camoufox_agent.py                                               ║
║                                                                          ║
║  TIER 4 : Camoufox — Patched Firefox Anti-Detect Browser                ║
║                                                                          ║
║  WHY TIER 4?                                                             ║
║  Tiers 1-3 all use Chromium. When Google or Cloudflare detects a        ║
║  pattern across all Chromium-based bots (same TLS fingerprint,          ║
║  same JS engine quirks), they can block ALL of them with a single       ║
║  rule. Camoufox uses Firefox's Gecko engine — a fundamentally           ║
║  different TLS signature, different JS behaviour, different UA pool.    ║
║  This is the "Plan Z" that breaks Chrome-only detection strategies.     ║
║                                                                          ║
║  Key differences vs Chromium tiers:                                     ║
║    ✓ Gecko engine → different TLS 1.3 cipher suite order                ║
║    ✓ Firefox User-Agent pool (20%+ market share vs Chrome 65%)         ║
║    ✓ Fingerprint spoofing at C++ level (not detectable via JS)          ║
║    ✓ BrowserForge auto-generates statistically realistic fingerprints   ║
║    ✓ human-like mouse movement (built-in, C++ implementation)           ║
║    ✓ navigator.webdriver = false (Juggler protocol, not CDP)            ║
║                                                                          ║
║  Install:                                                                ║
║      pip install camoufox                                                ║
║      python -m camoufox fetch      (downloads ~200MB Firefox binary)    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import re
from typing import Optional, List

from core import config
from common.anti_bot import action_delay_async, is_captcha_page
from core.logger import get_logger, alert
from common.captcha_solver import detect_captcha_type, solve_captcha_async

logger = get_logger(__name__)


from agents.base_agent import BaseBrowserAgent

class CamoufoxAgent(BaseBrowserAgent):
    """
    Tier 4 — Firefox-based anti-detect browser using Camoufox.

    Camoufox patches Firefox (Gecko engine) at the C++ level, making its
    fingerprint spoofing undetectable via JavaScript inspection. It uses
    BrowserForge to generate statistically realistic device fingerprints
    that match real-world distributions.

    This tier is the last resort when all Chromium-based tiers (1, 2, 3)
    have been exhausted. The fundamental change of browser engine (Chrome →
    Firefox) breaks detection rules that target Chromium-specific signatures.

    Lifecycle:
        agent = CamoufoxAgent()
        await agent.start()
        try:
            content = await agent.search_google_ai("query")
        finally:
            await agent.close()
    """

    def __init__(self, worker_id: int = 0, proxy: Optional[str] = None):
        self._worker_id = worker_id
        self._proxy = proxy
        self._browser = None    # AsyncCamoufox context manager instance
        self._page = None       # Active Firefox page / Playwright Page object
        self._playwright = None # Underlying Playwright instance (via Camoufox)

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Launch Camoufox (patched Firefox) with automatic fingerprint generation.

        Camoufox injects realistic fingerprints at the C++ level before
        the browser even starts — not via JS, making it fully undetectable.
        """
        try:
            from camoufox.async_api import AsyncCamoufox  # type: ignore
        except ImportError:
            raise RuntimeError(
                "camoufox is not installed.\n"
                "Run: pip install camoufox && python -m camoufox fetch"
            )

        logger.info("[Camoufox] 🦊 Launching patched Firefox (Tier 4)...")

        # Build proxy config if provided
        proxy_cfg = None
        if self._proxy:
            proxy_cfg = {"server": self._proxy}

        # AsyncCamoufox auto-generates a statistically realistic fingerprint
        # using BrowserForge (OS, UA, screen, GPU, language based on real traffic).
        # headless=False: Firefox appears as a normal visible browser (most stealthy).
        # geoip=True: auto-calculate locale/timezone from proxy IP to avoid mismatch.
        self._camoufox_ctx = AsyncCamoufox(
            headless=False,
            geoip=bool(self._proxy),      # Only geoip-match if using a proxy
            proxy=proxy_cfg,
            os="windows",                  # Spoof Windows (largest market share = less suspicious)
            block_webrtc=True,             # Prevent WebRTC IP leaks
        )

        self._browser = await self._camoufox_ctx.__aenter__()

        # Open a fresh page
        self._page = await self._browser.new_page()

        alert("INFO", "Camoufox session started", {
            "worker": self._worker_id,
            "proxy": self._proxy or "direct",
            "engine": "Firefox/Gecko",
        })
        logger.info("[Camoufox] ✅ Firefox ready — C++-level fingerprint active.")

    async def close(self) -> None:
        """Stop Camoufox and release all resources."""
        try:
            if self._page:
                await self._page.close()
            if hasattr(self, "_camoufox_ctx") and self._camoufox_ctx:
                await self._camoufox_ctx.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            self._browser = self._page = None
            logger.info("[Camoufox] Firefox closed.")

    # ─────────────────────────────────────────────────────────────────
    # NAVIGATION
    # ─────────────────────────────────────────────────────────────────

    async def goto_url(self, url: str) -> bool:
        """Navigate to a URL. Returns True on success."""
        if not self._page:
            return False
        try:
            logger.info(f"[Camoufox] → {url}")
            await self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await action_delay_async("navigate")
            await self._handle_captcha_if_present()
            return True
        except Exception as exc:
            logger.error(f"[Camoufox] Navigation error: {exc}")
            return False

    async def get_page_source(self) -> str:
        """Return raw HTML of the current page."""
        if not self._page:
            return ""
        try:
            return await self._page.content()
        except Exception:
            return ""

    # ─────────────────────────────────────────────────────────────────
    # SEARCH METHODS  (mirrors PatchrightAgent interface)
    # ─────────────────────────────────────────────────────────────────

    async def search_google_ai(self, query: str) -> Optional[str]:
        """
        Search Google AI Mode via direct URL navigation.
        Uses Firefox fingerprint — Google sees a real Firefox user.

        Returns full page text for downstream regex/LLM extraction.
        """
        import urllib.parse
        if not self._page:
            return None
        try:
            from common.search_engine import generate_google_ai_url
            url = generate_google_ai_url(query)

            logger.info(f"[Camoufox] 🔍 Google AI Mode (Firefox): {query}")
            await self._page.goto(url, wait_until="load", timeout=30000)
            await action_delay_async("read_wait")

            await self._handle_google_cookies()
            await self._handle_captcha_if_present()

            content = await self.get_page_source()
            if not content or len(content) < 500:
                logger.warning("[Camoufox] Empty page after AI Mode search.")
                return None

            logger.info(f"[Camoufox] ✅ AI Mode — {len(content)} chars (Firefox).")
            return content

        except Exception as exc:
            logger.error(f"[Camoufox] search_google_ai error: {exc}")
            return None

    async def search_google_ai_mode(self, query: str) -> Optional[str]:
        """Alias for search_google_ai — HybridEngine compatibility."""
        return await self.search_google_ai(query)

    async def submit_google_search(self, query: str) -> bool:
        """
        Navigate to Google standard search results page.
        """
        import urllib.parse
        if not self._page:
            return False
        try:
            url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
            logger.info(f"[Camoufox] 🔍 Google Search (Firefox): {query}")
            await self._page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await action_delay_async("navigate")
            await self._handle_google_cookies()
            await self._handle_captcha_if_present()

            content = await self.get_page_source()
            if content and len(content) > 500:
                logger.info(f"[Camoufox] ✅ submit_google_search — {len(content)} chars.")
                return True
            logger.warning("[Camoufox] submit_google_search — empty or blocked.")
            return False
        except Exception as exc:
            logger.error(f"[Camoufox] submit_google_search error: {exc}")
            return False


    async def crawl_website(self, url: str) -> str:
        """
        Visit a URL and return visible page text.
        Used by HybridEngine as Tier 4 deep-scraper fallback.
        """
        if not await self.goto_url(url):
            return ""
        try:
            html = await self.get_page_source()
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:8000]
        except Exception as exc:
            logger.error(f"[Camoufox] crawl_website error: {exc}")
            return ""

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        """
        Deep search using Google Gemini (Firefox/Camoufox).
        """
        if not self._page:
            return None
        try:
            logger.info(f"[Camoufox] 🤖 Gemini (Firefox): {query}")
            await self._page.goto(config.GEMINI_URL, wait_until="load")
            await asyncio.sleep(4)
            
            # Find input
            selectors = ["div[role='combobox']", ".ql-editor", "textarea"]
            chat_input = None
            for s in selectors:
                if await self._page.locator(s).count() > 0:
                    chat_input = self._page.locator(s).first
                    break
            
            if not chat_input:
                logger.warning("[Camoufox/Gemini] Could not find input.")
                return None
                
            await chat_input.click()
            await self._page.keyboard.type(query)
            await self._page.keyboard.press("Enter")
            
            # Stable response extraction
            last_text = ""
            stable_count = 0
            for _ in range(30):
                await asyncio.sleep(2)
                res_sel = [".model-response-text", "message-content"]
                current = None
                for rs in res_sel:
                    if await self._page.locator(rs).count() > 0:
                        current = await self._page.locator(rs).first.text_content()
                        break
                
                if current and current == last_text:
                    stable_count += 1
                    if stable_count >= 3:
                        return current.strip()
                else:
                    stable_count = 0
                    last_text = current or ""
            
            return last_text.strip() if last_text else None
        except Exception as exc:
            logger.error(f"[Camoufox] search_gemini_ai error: {exc}")
            return None

    # ─────────────────────────────────────────────────────────────────
    # CAPTCHA & COOKIE HELPERS
    # ─────────────────────────────────────────────────────────────────

    async def _handle_captcha_if_present(self) -> bool:
        """
        Detect and attempt CAPTCHA resolution.
        Camoufox's Firefox fingerprint prevents ~95% of CAPTCHAs;
        this covers the remaining edge cases.

        Returns True if page is usable, False if CAPTCHA unresolved.
        """
        try:
            content = await self._page.content()
        except Exception:
            return False

        if not is_captcha_page(content):
            return True

        logger.warning("[Camoufox] CAPTCHA detected (rate-limit, not fingerprint).")

        # Try API solver if configured
        try:
            captcha_type = detect_captcha_type(content)
            if captcha_type and getattr(config, "CAPTCHA_API_KEY", ""):
                solved = await solve_captcha_async(self._page, captcha_type)
                if solved:
                    logger.info("[Camoufox] ✅ CAPTCHA auto-solved.")
                    return True
        except Exception as exc:
            logger.debug(f"[Camoufox] Captcha solver error: {exc}")

        # Short wait then let circuit breaker handle it
        logger.warning("[Camoufox] CAPTCHA unresolved — waiting 10s, then escalating.")
        await asyncio.sleep(10)
        return False

    async def _handle_google_cookies(self) -> None:
        """Accept Google cookie consent banners if present."""
        try:
            selectors = [
                "button:has-text('Accept all')",
                "button:has-text('Accepter tout')",
                "button:has-text('I agree')",
                "#L2AGLb",
            ]
            for s in selectors:
                btn = self._page.locator(s)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    logger.info("[Camoufox] Cookie consent accepted.")
                    await asyncio.sleep(1)
                    break
        except Exception:
            pass
