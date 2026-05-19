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

from __future__ import annotations
import asyncio
import re
from typing import Optional, List, Any, Dict

from core import config
from common.anti_bot import action_delay_async, is_captcha_page
from infra.browsers.selectors import GENERIC_CHAT_INPUT_SELECTORS, GOOGLE_COOKIE_ACCEPT_SELECTORS
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

    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self.current_proxy: Optional[str] = None
        self._browser = None    # AsyncCamoufox context manager instance
        self._page = None       # Active Firefox page / Playwright Page object
        self._playwright = None # Underlying Playwright instance (via Camoufox)
        self._lock = asyncio.Lock()
        self._last_health_check = 0.0

    async def is_alive(self) -> bool:
        """Public health check with lock protection."""
        async with self._lock:
            if not self._page: return False
            try:
                await self._page.evaluate("1+1")
                return True
            except Exception:
                return False

    async def _ensure_page_locked(self) -> bool:
        """
        Defensive check: ensures self._page is not None AND the browser
        context is still responsive.
        """
        now = asyncio.get_event_loop().time()
        if self._page and (now - self._last_health_check < 5.0):
            return True

        if not self._page:
            await self._start_locked()
            if not self._page: return False

        try:
            # Heartbeat check
            await self._page.evaluate("1+1")
            self._last_health_check = now
            return True
        except Exception as e:
            logger.warning(f"[Camoufox] 💔 Firefox unresponsive: {e}. Resurrecting...")
            await self._close_locked()
            await self._start_locked()
            return self._page is not None

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch Camoufox (patched Firefox)."""
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        """
        Launch Camoufox (patched Firefox) with automatic fingerprint generation.
        """
        if self._page:
            return
            
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
        if not self.current_proxy and config.PROXY_ENABLED:
            from common.proxy_manager import get_next_proxy
            self.current_proxy = await get_next_proxy()

        if self.current_proxy:
            proxy_cfg = {"server": self.current_proxy}

        # AsyncCamoufox auto-generates a statistically realistic fingerprint
        # using BrowserForge (OS, UA, screen, GPU, language based on real traffic).
        # headless=False: Firefox appears as a normal visible browser (most stealthy).
        # geoip=True: auto-calculate locale/timezone from proxy IP to avoid mismatch.
        self._camoufox_ctx = AsyncCamoufox(
            headless=getattr(config, "HEADLESS", False),
            geoip=bool(self.current_proxy),      # Only geoip-match if using a proxy
            proxy=proxy_cfg,
            os="windows",                  # Spoof Windows (largest market share = less suspicious)
            block_webrtc=True,             # Prevent WebRTC IP leaks
        )

        self._browser = await self._camoufox_ctx.__aenter__()

        # Open a fresh page
        self._page = await self._browser.new_page()

        alert("INFO", "Camoufox session started", {
            "worker": self._worker_id,
            "proxy": self.current_proxy or "direct",
            "engine": "Firefox/Gecko",
        })
        logger.info("[Camoufox] ✅ Firefox ready — C++-level fingerprint active.")

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy and restart the browser session."""
        async with self._lock:
            from common.proxy_manager import get_next_proxy
            new_proxy = await get_next_proxy()
            if new_proxy:
                logger.info(f"[Camoufox] ♻️  Rotating proxy to: {new_proxy}")
                self.current_proxy = new_proxy
                await self._close_locked()
                await self._start_locked()
            else:
                logger.warning("[Camoufox] No proxies available for rotation.")

    async def close(self) -> None:
        """Stop Camoufox and release all resources."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
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
        async with self._lock:
            if not await self._ensure_page_locked():
                return False
            try:
                logger.info(f"[Camoufox] → {url}")
                await self._page.goto(url, wait_until="domcontentloaded", timeout=self.get_adaptive_timeout_ms(20000))
                await action_delay_async("navigate")
                await self._handle_captcha_if_present_locked()
                
                # Post-navigation health check (detect immediate blocks)
                content = await self._page.content()
                if self.is_block_response(content):
                    await self.report_proxy_error(self.current_proxy, 403)
                    await self.rotate_proxy()
                    return False

                return True
            except Exception as exc:
                logger.error(f"[Camoufox] Navigation error: {exc}")
                if self.is_block_response(exc):
                    await self.report_proxy_error(self.current_proxy, 403)
                return False

    async def get_page_source(self) -> str:
        """Return raw HTML of the current page with caching."""
        async with self._lock:
            if not self._page:
                return self._last_content
            try:
                content = await self._page.content()
                if content:
                    self._last_content = content
                return self._last_content
            except Exception:
                return self._last_content

    # ─────────────────────────────────────────────────────────────────
    # SEARCH METHODS  (mirrors PatchrightAgent interface)
    # ─────────────────────────────────────────────────────────────────

    async def search_google_ai(self, prompt: str, **kwargs) -> Optional[str]:
        """Search Google AI Mode (Firefox)."""
        ai_mode_url = kwargs.get("ai_mode_url")
        row = kwargs.get("row")
        async with self._lock:
            if not await self._ensure_page_locked():
                return None
            try:
                from common.search_engine import generate_google_ai_url, extract_search_terms
                if ai_mode_url:
                    import urllib.parse
                    clean_query = extract_search_terms(prompt)
                    url = ai_mode_url + urllib.parse.quote_plus(clean_query)
                else:
                    url = generate_google_ai_url(prompt)

                logger.info(f"[Camoufox] 🔍 Google AI Mode (Firefox): {prompt}")
                await self._page.goto(url, wait_until="load", timeout=self.get_adaptive_timeout_ms(30000))
                await action_delay_async("read_wait")

                # Detect immediate block
                page_content = await self._page.content()
                if self.is_block_response(page_content):
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                    return None

                await self._handle_google_cookies_locked()
                await self._handle_captcha_if_present_locked()

                content = await self._page.content() if self._page else ""
                if not content or len(content) < 500:
                    logger.warning("[Camoufox] Empty page after AI Mode search.")
                    return None

                logger.info(f"[Camoufox] ✅ AI Mode — {len(content)} chars (Firefox).")
                return content

            except Exception as exc:
                logger.error(f"[Camoufox] search_google_ai error: {exc}")
                if self.is_block_response(exc):
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                return None

    async def search_google_ai_mode(self, prompt: str, **kwargs) -> Optional[str]:
        """Alias for search_google_ai — HybridEngine compatibility."""
        return await self.search_google_ai(prompt, **kwargs)

    async def search_google_ai_interactive(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Interactive high-stealth search flow for Camoufox.
        """
        return await self.search_google_ai(prompt, **kwargs)

    async def submit_google_search(self, prompt: str) -> bool:
        """Navigate to Google standard search results page."""
        async with self._lock:
            if not await self._ensure_page_locked():
                return False
            try:
                import urllib.parse
                url = f"https://www.google.com/search?q={urllib.parse.quote_plus(prompt)}"
                logger.info(f"[Camoufox] 🔍 Google Search (Firefox): {prompt}")
                await self._page.goto(url, wait_until="domcontentloaded", timeout=self.get_adaptive_timeout_ms(20000))
                await action_delay_async("navigate")
                await self._handle_google_cookies_locked()
                await self._handle_captcha_if_present_locked()

                content = await self._page.content() if self._page else ""
                
                # Detect immediate block
                if content and self.is_block_response(content):
                    await self.report_proxy_error(self.current_proxy, 403)
                    await self.rotate_proxy()
                    return False

                if content and len(content) > 500:
                    logger.info(f"[Camoufox] ✅ submit_google_search — {len(content)} chars.")
                    return True
                logger.warning("[Camoufox] submit_google_search — empty or blocked.")
                return False
            except Exception as exc:
                logger.error(f"[Camoufox] submit_google_search error: {exc}")
                if self.is_block_response(exc):
                    await self.report_proxy_error(self.current_proxy, 403)
                return False


    async def crawl_website(self, url: str, **kwargs) -> str:
        """Visit a URL and return body text (Firefox).
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

    async def search_gemini_ai(self, prompt: str, **kwargs) -> Optional[str]:
        """
        Deep search using Google Gemini (Firefox/Camoufox).
        """
        async with self._lock:
            if not await self._ensure_page_locked():
                return None
            try:
                logger.info(f"[Camoufox] 🤖 Gemini (Firefox): {prompt}")
                await self._page.goto(config.GEMINI_URL, wait_until="load")
                await asyncio.sleep(4)
                
                if not self._page: return None
                
                # Find input
                selectors = GENERIC_CHAT_INPUT_SELECTORS
                chat_input = None
                for s in selectors:
                    if not self._page: return None
                    try:
                        if await self._page.locator(s).count() > 0:
                            chat_input = self._page.locator(s).first
                            break
                    except Exception: continue
                
                if not chat_input:
                    logger.warning("[Camoufox/Gemini] Could not find input.")
                    return None
                    
                await chat_input.click()
                if not self._page: return None
                await self._page.keyboard.type(prompt)
                await self._page.keyboard.press("Enter")
                
                # Stable response extraction
                last_text = ""
                stable_count = 0
                for _ in range(30):
                    await asyncio.sleep(2)
                    if not self._page: return last_text.strip() if last_text else None
                    
                    res_sel = [".model-response-text", "message-content"]
                    current = None
                    for rs in res_sel:
                        try:
                            if await self._page.locator(rs).count() > 0:
                                current = await self._page.locator(rs).first.text_content()
                                break
                        except Exception: continue
                    
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
                if self.is_block_response(exc):
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                return None

    # ─────────────────────────────────────────────────────────────────
    # CAPTCHA & COOKIE HELPERS
    # ─────────────────────────────────────────────────────────────────

    async def _handle_captcha_if_present_locked(self) -> bool:
        """
        Detect and attempt CAPTCHA resolution. (Locked)
        """
        if not self._page:
            return False
        try:
            content = await self._page.content()
        except Exception:
            return False

        if not is_captcha_page(content):
            return True

        # Report proxy error for IP ban if it looks like a hard block
        if self.is_block_response(content):
            if self.current_proxy:
                await self.report_proxy_error(self.current_proxy, 403)

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
        logger.warning("[Camoufox] CAPTCHA unresolved — waiting 10s, then rotating.")
        await self.rotate_proxy()
        return False

    async def _handle_google_cookies_locked(self) -> None:
        """Accept Google cookie consent banners if present (Locked)."""
        if not self._page:
            return
        try:
            selectors = GOOGLE_COOKIE_ACCEPT_SELECTORS
            for s in selectors:
                if not self._page: return
                try:
                    btn = self._page.locator(s)
                    if await btn.count() > 0 and await btn.is_visible():
                        await btn.click()
                        logger.info("[Camoufox] Cookie consent accepted.")
                        await asyncio.sleep(1)
                        break
                except Exception: continue
        except Exception:
            pass
