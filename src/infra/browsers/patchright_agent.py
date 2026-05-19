"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/patchright_agent.py                                             ║
║                                                                          ║
║  Patchright browser agent. (ASYNC VERSION)                               ║
║                                                                          ║
║  Search strategy (no AI/LLM modes):                                     ║
║    1. Google search with raw identifiers (name + address + SIREN)        ║
║    2. Scan the FULL page HTML for phone via tel: hrefs & regex           ║
║    3. Also check Google Knowledge Panel selectors                        ║
║    No Gemini / DuckDuckGo AI fallback for phone searches.               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import asyncio
import random
import re
import json
import urllib.parse
import os
from pathlib import Path
from typing import Optional, List, Dict, Any

from patchright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)


from core import config
from agents.base_agent import BaseBrowserAgent
from common.anti_bot import (
    get_random_user_agent,
    short_delay,
    is_captcha_page,
    wait_for_human_captcha_solve,
    get_fingerprint_bundle,
    build_cdp_injection_script,
    action_delay_async,
)
from core.logger import get_logger, alert

logger = get_logger(__name__)

from infra.browsers.selectors import (
    GENERIC_CHAT_INPUT_SELECTORS,
    GOOGLE_AI_MODE_TAB_SELECTORS,
    GOOGLE_AI_RESPONSE_SELECTORS,
    GOOGLE_COOKIE_ACCEPT_SELECTORS,
)

# ── Google Knowledge Panel / Instant Answer selectors ──────────────────────
# These CSS selectors target common locations where Google displays phone numbers
# directly on the search results page (no AI Overview needed).
GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"], textarea[title="Search"], input[title="Search"], textarea[title="Rechercher"], input[title="Rechercher"], [aria-label="Search"]'

# ── Gemini selectors (kept for SIREN/Name enrichment only, NOT phone) ──────
GEMINI_INPUT_SELECTORS   = GENERIC_CHAT_INPUT_SELECTORS
GEMINI_RESPONSE_SELECTORS = [
    ".model-response-text",
    "message-content",
    "div.message-content",
    ".response-container-content",
]


class PatchrightAgent(BaseBrowserAgent):
    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._playwright = None
        self._context: Optional[BrowserContext] = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        # Fingerprint bundle — regenerated on each start()
        self._fingerprint = None

        # Generate a unique profile path for this worker to avoid locking conflicts
        self.profile_path = config.get_worker_profile_path(worker_id, "patchright")

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch Patchright browser context."""
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        """Internal lock-free start."""
        if self._page: return
        logger.info("[Patchright] Starting Chrome with your profile...")
        if not self._playwright:
            self._playwright = await async_playwright().start()

        self._fingerprint = get_fingerprint_bundle()
        vp = self._fingerprint["viewport"]
        launch_args = [f"--window-size={vp['width']},{vp['height']}"]
        
        # 🛡️ Hardened Sandbox Fix for Root/Docker
        if os.getuid() == 0:
            logger.info("[Patchright] 🛡️ Running as ROOT: Disabling sandbox flags.")
            launch_args.extend(["--no-sandbox", "--disable-setuid-sandbox", "--disable-dev-shm-usage"])

        geolocation = None
        permissions = []
        if config.SET_GEOLOCATION:
            geolocation = {"latitude": config.DEFAULT_LAT, "longitude": config.DEFAULT_LON}
            permissions = ["geolocation"]

        proxy_settings = None
        if config.PROXY_ENABLED:
            if not self.current_proxy:
                from common.proxy_manager import get_next_proxy
                self.current_proxy = await get_next_proxy()
            
            if self.current_proxy:
                proxy_settings = {"server": self.current_proxy}

        try:
            self._context = await self._playwright.chromium.launch_persistent_context(
                user_data_dir=self.profile_path,
                headless=getattr(config, "HEADLESS", False),
                executable_path=config.CHROMIUM_BINARY_PATH or None,
                args=launch_args,
                viewport={"width": vp["width"], "height": vp["height"]},
                user_agent=self._fingerprint["user_agent"],
                geolocation=geolocation,
                permissions=permissions,
                ignore_https_errors=True,
                proxy=proxy_settings,
            )

            fp_script = build_cdp_injection_script(self._fingerprint)
            await self._context.add_init_script(script=fp_script)
            self._page = self._context.pages[0] if self._context.pages else await self._context.new_page()
            logger.info("[Patchright] ✅ Ready.")
        except Exception as e:
            logger.error(f"[Patchright] Startup failed: {e}")
            self._context = self._page = None
            raise

    async def close(self) -> None:
        """Gracefully stop the browser."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
        try:
            if self._context:
                await self._context.close()
            if self._playwright:
                await self._playwright.stop()
        except Exception:
            pass
        finally:
            self._context = self._page = self._playwright = None
            logger.info("[Patchright] Browser closed.")

    async def is_alive(self) -> bool:
        """Public health check with lock protection. Passive."""
        async with self._lock:
            if not self._page: return False
            try:
                # Playwright heartbeat
                await self._page.evaluate("1+1", timeout=self.get_adaptive_timeout_ms(2000))
                return True
            except Exception:
                return False

    # ── Resilience ────────────────────────────────────────────────────────
    
    async def _ensure_page_locked(self) -> bool:
        """
        Check if the page is responsive via a heartbeat.
        Automatically restarts if the page is dead or None.
        """
        import time
        now = time.time()
        # 5s health-check cache
        if self._page and getattr(self, "_last_health_check", 0) > (now - 5):
            return True

        if not self._page or not self._context:
            logger.info("[Patchright] 🔄 Session missing/dead. Starting...")
            await self._start_locked()
            return self._page is not None

        try:
            # Heartbeat: simple JS eval
            await self._page.evaluate("1+1", timeout=self.get_adaptive_timeout_ms(5000))
            self._last_health_check = now
            return True
        except Exception as e:
            logger.warning(f"[Patchright] 💔 Page unresponsive: {e}. Resurrecting...")
            await self._close_locked()
            await self._start_locked()
            return self._page is not None

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy and restart the browser context."""
        async with self._lock:
            await self._rotate_proxy_locked()

    async def get_page_source(self) -> str:
        """Return raw HTML content."""
        async with self._lock:
            return await self._get_page_source_locked()

    async def _get_page_source_locked(self) -> str:
        if not self._page:
            return self._last_content
        try:
            content = await self._page.content()
            self._last_content = content or ""
            return self._last_content
        except Exception:
            return self._last_content


    # ── Main Search Method (phone-focused, NO AI/LLM) ─────────────────────


    async def submit_google_search(self, prompt: str) -> bool:
        """Navigate to Google and submit search query."""
        async with self._lock:
            return await self._submit_google_search_locked(prompt)

    async def _submit_google_search_locked(self, prompt: str) -> bool:
        if not await self._ensure_page_locked():
            return False
        
        page = self._page
        if not page: return False
        
        try:
            logger.info(f"[Patchright] 🔍 Google Search: {prompt}")
            await page.goto(config.GOOGLE_URL, wait_until="load", timeout=self.get_adaptive_timeout_ms(30000))
            await self._handle_google_cookies_locked(page)
            await self._handle_captcha_if_present_locked(page)
            
            # Re-check page after potential rotation in captcha handler
            page = self._page
            if not page: return False

            # Post-navigation health check (detect immediate blocks)
            content = await page.content()
            if self.is_block_response(content):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return False

            # Use a robust helper to find and type
            search_input = await self._find_input_locked(page, GOOGLE_SEARCH_INPUT)
            if search_input:
                await search_input.click()
                await self._human_type_locked(page, prompt)
                await search_input.press("Enter")
                await asyncio.sleep(2)
                return True
            return False
        except Exception as e:
            logger.error(f"[Patchright] Google Search Submission Error: {e}")
            if self.is_block_response(e):
                await self.report_proxy_error(self.current_proxy, 403)
            return False

    async def _navigate_and_search_locked(self, page: Page, prompt: str) -> None:
        """Internal lock-free navigate and search."""
        logger.info(f"[Google] Search: {prompt}")
        await page.goto(config.GOOGLE_URL, wait_until="load")
        await self._handle_google_cookies_locked(page)
        await self._handle_captcha_if_present_locked(page)
        
        page = self._page # Might have rotated
        if not page: return

        search_box = await self._find_input_locked(page, GOOGLE_SEARCH_INPUT)
        if search_box:
            await search_box.click()
            await self._human_type_locked(page, prompt)
            await search_box.press("Enter")
            await asyncio.sleep(2)
            await self._click_ai_mode_tab_locked(page)

    async def _click_ai_mode_tab_locked(self, page: Page) -> bool:
        """Internal lock-free click AI tab."""
        if not page: return False
        tab_selectors = GOOGLE_AI_MODE_TAB_SELECTORS
        for selector in tab_selectors:
            try:
                # Use locator only if page is valid
                if not self._page: break
                tab = self._page.locator(selector).first
                if await tab.count() > 0 and await tab.is_visible(timeout=self.get_adaptive_timeout_ms(1500)):
                    await tab.click()
                    logger.info(f"🤖 [AI Mode Tab] Clicked: '{selector}'")
                    await asyncio.sleep(2.5)
                    return True
            except Exception: continue
        return False


    async def goto_url(self, url: str) -> bool:
        """Navigate to a specific URL."""
        async with self._lock:
            return await self._goto_url_locked(url)

    async def _goto_url_locked(self, url: str) -> bool:
        if not await self._ensure_page_locked():
            return False
        
        page = self._page
        if not page: return False
        try:
            await self._page.goto(url, wait_until="domcontentloaded", timeout=self.get_adaptive_timeout_ms(15000))
            
            # Post-navigation health check (detect immediate blocks)
            content = await self._page.content()
            if self.is_block_response(content):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return False
                
            return True
        except Exception as e:
            logger.debug(f"[Patchright] Failed to visit {url}: {e}")
            if self.is_block_response(e):
                await self.report_proxy_error(self.current_proxy, 403)
            return False

    async def crawl_website(self, url: str, **kwargs) -> str:
        """Deep crawl of a website."""
        async with self._lock:
            return await self._crawl_website_locked(url)

    async def _crawl_website_locked(self, url: str) -> str:
        if not await self._goto_url_locked(url):
            return ""
        
        try:
            page = self._page
            if not page: return ""
            logger.info(f"🕸️ [Patchright] DeepCrawl: {url}")
            await asyncio.sleep(2)
            
            content_text = await page.inner_text("body")
            all_text = [f"--- PAGE: {url} ---\n" + content_text]
            
            # Link discovery for contact pages
            links = await page.locator("a").all()
            found_sublinks = []
            
            for link in links:
                try:
                    if not self._page: break
                    name = (await link.inner_text() or "").lower()
                    href = (await link.get_attribute("href") or "").lower()
                    
                    if any(k in name or k in href for k in config.CONTACT_KEYWORDS):
                        full_url = await link.get_attribute("href")
                        if full_url and full_url.startswith("http") and full_url != url:
                            found_sublinks.append(full_url)
                        elif full_url and full_url.startswith("/"):
                            from urllib.parse import urljoin
                            found_sublinks.append(urljoin(url, full_url))
                except Exception: continue
                
                if len(found_sublinks) >= 2: break 

            # Visit subpages
            for sub in list(set(found_sublinks)):
                try:
                    if not self._page: break
                    logger.info(f"   ∟ Visiting subpage: {sub}")
                    await page.goto(sub, wait_until="domcontentloaded", timeout=self.get_adaptive_timeout_ms(10000))
                    await asyncio.sleep(1)
                    if self._page:
                        all_text.append(f"\n--- PAGE: {sub} ---\n" + await page.inner_text("body"))
                except Exception:
                    continue
            
            return "\n".join(all_text)
        except Exception as e:
            logger.error(f"[Patchright] Crawl error for {url}: {e}")
            return ""

    async def search_google_ai_mode(self, prompt: str, **kwargs) -> Optional[str]:
        """PRIMARY SEARCH METHOD — TIER 0"""
        ai_mode_url = kwargs.get("ai_mode_url")
        async with self._lock:
            if not await self._ensure_page_locked():
                return None
            page = self._page
            if not page: return None
            
            try:
                from common.search_engine import generate_google_ai_url, extract_search_terms
                
                if ai_mode_url:
                    import urllib.parse
                    clean_query = extract_search_terms(prompt)
                    url = ai_mode_url + urllib.parse.quote_plus(clean_query)
                else:
                    url = generate_google_ai_url(prompt)
                
                logger.info(f"🤖 [AI Mode] Navigating: {url}")
                await page.goto(url, wait_until="load", timeout=self.get_adaptive_timeout_ms(30000))
                
                # Detect immediate block
                page_content = await page.content()
                if self.is_block_response(page_content):
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                    await self.rotate_proxy()
                    return None

                await self._handle_google_cookies_locked(page)
                await self._handle_captcha_if_present_locked(page)
                
                page = self._page # Re-capture
                if not page: return None

                logger.info("⏳ [AI Mode] Waiting for response...")
                return await self._wait_for_ai_mode_response_locked(page, timeout_sec=self.get_adaptive_timeout_sec(25))
            except Exception as e:
                logger.error(f"[AI Mode] Error: {e}")
                if self.is_block_response(e):
                    await self.report_proxy_error(self.current_proxy, 403)
                return None

    async def _wait_for_ai_mode_response_locked(self, page: Page, timeout_sec: int = 25) -> Optional[str]:
        """Internal lock-free wait."""
        ai_response_selectors = GOOGLE_AI_RESPONSE_SELECTORS
        deadline = asyncio.get_event_loop().time() + timeout_sec
        prev_text = ""
        stable_count = 0
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.5)
            for selector in ai_response_selectors:
                try:
                    elements = await page.locator(selector).all()
                    texts = [await el.inner_text() for el in elements[:5]]
                    combined = "\n".join([t for t in texts if t and len(t) > 30])
                    if combined:
                        if combined == prev_text:
                            stable_count += 1
                            if stable_count >= 2: return combined
                        else:
                            prev_text = combined
                            stable_count = 0
                        break
                except Exception: continue
        return prev_text if prev_text else None

    @staticmethod
    def parse_ai_mode_json(raw_text: str) -> dict:
        """
        Extracts and parses the JSON block from Google AI Mode's response.
        Wrapper around the shared utility for backward compatibility.
        """
        from common.json_parser import parse_ai_mode_json as parse_utils
        res = parse_utils(raw_text)
        return res if res is not None else {}

    async def _handle_google_cookies_locked(self, page: Page) -> None:
        """Internal lock-free cookie handler."""
        try:
            selectors = GOOGLE_COOKIE_ACCEPT_SELECTORS
            for s in selectors:
                btn = page.locator(s)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1)
                    break
        except Exception: pass

    async def _handle_captcha_if_present_locked(self, page: Page) -> bool:
        """Internal lock-free CAPTCHA handler."""
        try:
            content = await page.content()
            if not is_captcha_page(content): return False
            logger.warning("[Google] CAPTCHA detected.")
            
            # Report proxy error for IP ban if it looks like a hard block
            if self.is_block_response(content):
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)

            from common.captcha_solver import detect_captcha_type, solve_captcha_async
            captcha_type = detect_captcha_type(content)
            if captcha_type and getattr(config, "CAPTCHA_API_KEY", ""):
                solved = await solve_captcha_async(page, captcha_type)
                if solved: return False # Page is fine now
            
            # Rotation if failed
            logger.warning("[Google] CAPTCHA blocked. Rotating...")
            await self._rotate_proxy_locked()
            return True
        except Exception: return False

    async def _rotate_proxy_locked(self) -> None:
        """Internal lock-free rotation."""
        from common.proxy_manager import get_next_proxy
        new_proxy = await get_next_proxy()
        if new_proxy:
            self.current_proxy = new_proxy
            await self._close_locked()
            await self._start_locked()

    async def search_gemini_ai(self, prompt: str, **kwargs) -> Optional[str]:
        """Deep search using Google Gemini."""
        async with self._lock:
            if not await self._ensure_page_locked(): return None
            page = self._page
            if not page: return None
            try:
                logger.info(f"🚀 [Gemini] search: {prompt}")
                await page.goto(config.GEMINI_URL, wait_until="load")
                chat_input = None
                for s in GEMINI_INPUT_SELECTORS:
                    chat_input = await self._find_input_locked(page, s)
                    if chat_input: break
                if not chat_input: return None
                await chat_input.click()
                await self._human_type_locked(page, prompt)
                await page.keyboard.press("Enter")
                return await self._wait_for_streaming_response_locked(page, GEMINI_RESPONSE_SELECTORS)
            except Exception as e:
                logger.error(f"[Gemini] Error: {e}")
                if self.is_block_response(e):
                    await self.report_proxy_error(self.current_proxy, 403)
                return None

    async def _find_input_locked(self, page: Page, selector: str, timeout_ms: int = 5000):
        if not page: return None
        try:
            await page.wait_for_selector(selector, timeout=timeout_ms)
            if not self._page: return None
            return page.locator(selector).first
        except Exception: return None

    async def _human_type_locked(self, page: Page, text: str) -> None:
        if not page: return
        for char in text:
            try:
                if not self._page: break
                await page.keyboard.type(char)
                await asyncio.sleep(random.uniform(0.04, 0.12))
            except Exception: break

    async def _wait_for_streaming_response_locked(self, page: Page, selectors: list) -> Optional[str]:
        start = asyncio.get_event_loop().time()
        last_text = ""
        stable_count = 0
        while asyncio.get_event_loop().time() - start < 60:
            current = await self._extract_first_available_locked(page, selectors) or ""
            if current and current == last_text:
                stable_count += 1
                if stable_count >= 4: return current
            else:
                stable_count = 0
                last_text = current
            await asyncio.sleep(1)
        return last_text or None

    async def _extract_first_available_locked(self, page: Page, selectors: list) -> Optional[str]:
        if not page: return None
        for s in selectors:
            try:
                if not self._page: break
                text = await page.locator(s).first.text_content(timeout=self.get_adaptive_timeout_ms(2000))
                if text and text.strip(): return text.strip()
            except Exception: continue
        return None

    async def search_google_ai(self, prompt: str, **kwargs) -> Optional[str]:
        """Legacy AI search fallback."""
        return await self.search_google_ai_mode(prompt, **kwargs)

    async def search_google_ai_interactive(self, prompt: str, **kwargs) -> Optional[str]:
        """Interactive high-stealth search flow."""
        return await self.search_google_ai_mode(prompt, **kwargs)
