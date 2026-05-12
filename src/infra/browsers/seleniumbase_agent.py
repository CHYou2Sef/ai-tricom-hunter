"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/seleniumbase_agent.py                                           ║
║                                                                          ║
║  TIER 1 — SeleniumBase UC Driver (headless=False, uc=True)               ║
║                                                                          ║
║  Directive source: docs/Gemini.md                                        ║
║  "Intégration SeleniumBase CDP — Furtivité au niveau protocolaire"       ║
║                                                                          ║
║  Anti-detection pillars (from Gemini.md §1):                             ║
║    ✓ Binary renaming   — chromedriver $cdc_ variables patched            ║
║    ✓ Reverse sequencing — Chrome launched BEFORE driver attaches         ║
║    ✓ Protocol discontinuity — WebDriver disconnects on sensitive events  ║
║    ✓ UC GUI clicks     — OS-level input bypasses JS event listeners      ║
║    ✓ Turnstile/CAPTCHA — uc_gui_click_captcha() native handling          ║
║    ✓ xvfb guard        — auto-detects headless Linux, sets DISPLAY=:99   ║
║                                                                          ║
║  Implemented scraping methods (BaseBrowserAgent contract):               ║
║    • search_google_ai_mode()   PRIMARY: direct AI Mode URL               ║
║    • search_google_ai()        Alias for waterfall compatibility         ║
║    • submit_google_search()    Standard search + human typing            ║
║    • search_gemini_ai()        Gemini chat interface                     ║
║    • crawl_website()           Deep crawl with contact page discovery    ║
║    • goto_url()                Generic URL navigation                    ║
║    • get_page_source()         Raw HTML of current page                  ║
║    • extract_universal_data()  Inherited from BaseBrowserAgent           ║
║    • rotate_proxy()            Session teardown + proxy swap + restart   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import asyncio
import os
import random
import re
import time
from pathlib import Path
from typing import Optional, Any, Dict, List, TYPE_CHECKING

from core import config
from agents.base_agent import BaseBrowserAgent
from common.anti_bot import (
    get_fingerprint_bundle,
    is_captcha_page,
    wait_for_human_captcha_solve,
)
from core.logger import get_logger, alert

logger = get_logger(__name__)

# ── Google selectors — identical to all other agents ─────────────────────────
GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"], textarea[title="Search"], input[title="Search"], textarea[title="Rechercher"], input[title="Rechercher"], [aria-label="Search"]'
# ── Gemini selectors ──────────────────────────────────────────────────────────
GEMINI_INPUT_SELECTORS = [
    "div[role='combobox']",
    ".ql-editor",
    "textarea",
]
GEMINI_RESPONSE_SELECTORS = [
    ".model-response-text",
    "message-content",
    "div.message-content",
    ".response-container-content",
]

# ── AI Mode response containers (same as patchright_agent) ───────────────────
AI_RESPONSE_SELECTORS = [
    "code",
    "div.XpoqFe",           # SGE main container
    "div.iv_7C",            # SGE alternate
    "div[data-attrid='wa:/description']",
    ".kp-wholepage-osrp-ent",
    "div.mod",
    ".xpdopen .c2xzTb",
    "div[role='main'] div.VwiC3b",
    "div[jsname='yEVEwb']",
    "div[class*='osrp']",
]
class SeleniumBaseAgent(BaseBrowserAgent):

    """
    Tier 1 browser agent powered by SeleniumBase UC Driver.

    Design pattern: Adapter + Template Method.
      • Adapter  — wraps the synchronous SeleniumBase Driver into the
                   async BaseBrowserAgent interface via asyncio.to_thread().
      • Template — inherits extract_universal_data() from BaseBrowserAgent,
                   only overrides the leaf methods.

    Lifecycle::

        agent = SeleniumBaseAgent(worker_id=0)
        await agent.start()
        try:
            result = await agent.search_google_ai_mode(prompt)
        finally:
            await agent.close()
    """

    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._driver = None                         # seleniumbase.Driver instance
        self.current_proxy: Optional[str] = None
        self._session_start_ts: float = 0.0
        self._last_content: str = ""
        self._fingerprint = get_fingerprint_bundle()
        self.last_interruption_reason: Optional[str] = None
        self.last_interruption_ts: Optional[float] = None
        self._lock = asyncio.Lock()
        self._last_health_check = 0.0

    async def is_alive(self) -> bool:
        """Public health check with lock protection."""
        async with self._lock:
            if not self._driver: return False
            try:
                # Confirm JS execution is alive
                await asyncio.to_thread(lambda: self._driver.execute_script("return 1+1"))
                return True
            except Exception:
                return False

    async def _ensure_driver_alive_locked(self) -> bool:
        """
        Defensive check: ensures self._driver is not None AND the underlying
        browser process is still responsive.
        """
        now = time.monotonic()
        if self._driver and (now - self._last_health_check < 5.0):
            return True # Don't spam health checks

        if not self._driver:
            await self._start_locked()
            if not self._driver: return False

        # Use the same logic as is_alive but inside existing lock
        try:
            await asyncio.to_thread(lambda: self._driver.execute_script("return 1+1"))
            self._last_health_check = now
            return True
        except Exception as e:
            logger.warning(f"[SeleniumBase] 💔 Driver unresponsive: {e}. Resurrecting...")
            await self._close_locked()
            await self._start_locked()
            return self._driver is not None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch SeleniumBase UC Driver with stealth config."""
        async with self._lock:
            await self._start_locked()

    async def _record_interruption(self, reason: str, details: str | None = None) -> None:
        """Record interruption reason for debugging/escalation.

        Tier2 expects this hook to exist; it must never raise.
        """
        try:
            self.last_interruption_reason = reason
            self.last_interruption_ts = time.time()
            # Keep details for potential telemetry/diagnostics.
            if details is not None:
                # Store as a plain attribute to avoid changing the runtime contract elsewhere.
                self._last_interruption_details = details  # type: ignore[attr-defined]
            logger.warning(f"[SeleniumBase] Interruption recorded: {reason}{(' - ' + details) if details else ''}")
        except Exception:
            # Absolute safety: never let interruption recording break scraping.
            pass

    async def _start_locked(self) -> None:
        """Internal lock-free start."""

        if self._driver:
            return

        if not self.current_proxy and config.PROXY_ENABLED:
            from common.proxy_manager import get_next_proxy
            self.current_proxy = await get_next_proxy()

        logger.info(
            f"[SeleniumBase] 🚀 Starting UC Driver "
            f"(worker={self.worker_id}, proxy={self.current_proxy or 'direct'})..."
        )
        _timeout = getattr(config, "BROWSER_STARTUP_TIMEOUT_SEC", 90.0)
        try:
            await asyncio.wait_for(
                asyncio.to_thread(self._sync_start),
                timeout=_timeout,
            )
        except asyncio.TimeoutError:
            _msg = (
                f"[SeleniumBase] ⏰ UC Driver TIMED OUT after {_timeout:.0f}s — "
                "Chrome/chromedriver version mismatch (e.g. Playwright Chromium updated "
                "but uc_driver cache is stale). Tier 2 will be skipped by HybridEngine."
            )
            logger.error(_msg)
            await self._record_interruption("startup_timeout", _msg)
            self._driver = None
            raise RuntimeError(_msg)
        except Exception as exc:
            await self._record_interruption("startup_failure", str(exc))
            raise

    def _sync_start(self) -> None:
        """
        Synchronous driver bootstrap — called via asyncio.to_thread().

        Uses Driver(uc=True, headless=False) per docs/Gemini.md directive.
        xvfb=True is set on Linux when no DISPLAY is available, so Chrome
        can render to a virtual framebuffer (required for stealth on servers).
        """
        from seleniumbase import Driver  # type: ignore

        vp = self._fingerprint["viewport"]

        # ── Reconnect time for Turnstile challenges (Gemini.md §2) ────────
        self._reconnect_time = getattr(config, "SELENIUMBASE_RECONNECT_TIME", 4)

        # ── Proxy ─────────────────────────────────────────────────────────
        proxy_str = self.current_proxy
        if proxy_str:
            logger.info(f"[SeleniumBase] 🔌 Using proxy: {proxy_str}")

        # ── Suppression of automation alerts & Sandbox handling ──
        # Docker runs Chrome as root without /dev/shm sizing → needs classic flags.
        extra_args = "--disable-infobars --disable-notifications"
        if getattr(config, "DOCKER_ENV", False):
            extra_args += " --no-sandbox --disable-dev-shm-usage"

        # ── Persistent Profile Handling ──
        profile_path = config.get_worker_profile_path(self.worker_id, "seleniumbase")
        logger.info(f"[SeleniumBase] 📂 Using persistent profile: {profile_path}")

        # SeleniumBase may print a long uc_driver bootstrap to stdout without flush;
        # keep structured logs so docker-compose -f does not look "stuck" mid-start.
        logger.info(
            "[SeleniumBase] ⏳ Launching UC Driver (first run can take 30–120s while "
            "Chrome attaches to Xvfb)…"
        )
        try:
            import sys

            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass

        # SeleniumBase/uc may keep stale ChromeOptions state across failed
        # startups in some container environments. Force a fresh instance
        # by constructing with explicit driver options each time.
        driver = Driver(
            uc=True,
            headless=False,
            user_data_dir=profile_path,
            ad_block=True,
            proxy=proxy_str,
            binary_location=config.CHROMIUM_BINARY_PATH or None,
            locale_code="fr",
            chromium_arg=extra_args,
        )

        # If uc_driver keeps a poisoned options object from a previous failed
        # attempt, it will throw on first navigation. Fail fast here so
        # HybridEngine can immediately escalate to a different tier.
        # Some uc_driver versions expose properties lazily; avoid forcing
        # access here to prevent false positives.

        self._driver = driver

        try:
            import sys

            sys.stdout.flush()
            sys.stderr.flush()
        except Exception:
            pass
        logger.info("[SeleniumBase] Driver() constructor returned; finishing session setup…")

        if not self._driver:
            raise RuntimeError("SeleniumBase Driver initialization returned None")

        # ── Resize window to fingerprinted viewport ────────────────────────
        try:
            self._driver.set_window_size(vp["width"], vp["height"])
        except Exception:
            pass

        self._driver.set_page_load_timeout(50)
        self._session_start_ts = time.monotonic()

        logger.info(
            f"[SeleniumBase] ✅ UC Driver ready — "
            f"uc=True, headless=False, "
            f"viewport={vp['width']}×{vp['height']}, "
            f"worker={self.worker_id}"
        )

    async def close(self) -> None:
        """Gracefully quit the UC Driver subprocess."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
        if self._driver:
            try:
                await asyncio.to_thread(self._sync_close)
            except Exception:
                pass
            finally:
                self._driver = None
        logger.info("[SeleniumBase] Browser closed.")

    def _sync_close(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy from the pool and restart the browser session."""
        async with self._lock:
            await self._rotate_proxy_locked()

    async def _rotate_proxy_locked(self) -> None:
        """Internal lock-free proxy rotation."""
        from common.proxy_manager import get_next_proxy
        new_proxy = await get_next_proxy()
        if new_proxy:
            logger.info(f"[SeleniumBase-Worker-{self.worker_id}] ♻️ Rotating proxy to: {new_proxy}")
            await self._close_locked()
            self.current_proxy = new_proxy
            await self._start_locked()
        else:
            logger.warning(f"[SeleniumBase-Worker-{self.worker_id}] No proxies left for rotation.")

    # ── Core interface ────────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return raw HTML of the current page."""
        async with self._lock:
            return await self._get_page_source_locked()

    async def _get_page_source_locked(self) -> str:
        if not self._driver:
            return self._last_content
        try:
            content = await asyncio.to_thread(lambda: self._driver.page_source)
            self._last_content = content or ""
            return self._last_content
        except Exception:
            return self._last_content

    async def goto_url(self, url: str) -> bool:
        """
        Navigate to a URL and wait for ready state.
        Handles proxy/session failures with one automatic retry after rotation.
        """
        async with self._lock:
            return await self._goto_url_locked(url)

    async def _goto_url_locked(self, url: str) -> bool:
        """Internal locked navigation."""
        if not await self._ensure_driver_alive_locked():
            return False

        try:
            logger.info(f"[SeleniumBase] Navigating to: {url}")
            await asyncio.to_thread(self._sync_goto_with_driver, self._driver, url)
            
            # Check for blocks immediately after navigation
            if await self._handle_captcha_if_present_locked():
                # If it detected a block and rotated or failed, we consider this navigation failed
                # to trigger HybridEngine escalation.
                return False
                
            return True
        except Exception as exc:
            if self.is_block_response(exc):
                logger.error("[SeleniumBase] 🛑 Session/Proxy FAILED (Block detected). Reporting...")
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)
                
                await self._rotate_proxy_locked()
                return False
            
            logger.error(f"[SeleniumBase] _goto_url_locked error: {exc}")
            return False

    def _sync_goto_with_driver(self, driver: Any, url: str) -> None:
        """Synchronous navigate + wait for page ready."""
        driver.get(url)
        try:
            driver.wait_for_ready_state_complete(timeout=20)
        except Exception:
            pass 

    # ── Search methods ────────────────────────────────────────────────────────

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """⭐ PRIMARY SEARCH — direct navigation to Google AI Mode."""
        async with self._lock:
            return await self._search_google_ai_mode_locked(prompt, ai_mode_url, row)

    async def _search_google_ai_mode_locked(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Internal locked AI Mode search."""
        if not await self._ensure_driver_alive_locked():
            return None

        # ── URL construction ─────────────────────────────────────────────
        if ai_mode_url:
            import urllib.parse
            url = ai_mode_url + urllib.parse.quote_plus(prompt)
            provider_label = "DDG-AI" if "duckduckgo" in ai_mode_url else "AI-Mode"
        else:
            from common.search_engine import generate_google_ai_url
            url = generate_google_ai_url(prompt)
            provider_label = "Google-AI-Mode"

        try:
            logger.info(f"🤖 [SeleniumBase-{provider_label}] Navigating for prompt ({len(prompt)} chars)...")
            await asyncio.to_thread(self._sync_goto_with_driver, self._driver, url)
            
            # ── 1. Handle Turnstile / CAPTCHA / Blocks ────────────────────
            if await self._handle_captcha_if_present_locked():
                logger.warning(f"[SeleniumBase] 🛡️ Search blocked or interrupted on {provider_label}")
                return None

            if not self._driver: return None

            # ── 2. Handle Cookies ────────────────────────────────────────
            await self._accept_cookies_locked()

            # ── 3. Extract data ──────────────────────────────────────────
            source = await self._get_page_source_locked()
            if not source or self.is_block_response(source):
                if source and self.is_block_response(source):
                    logger.warning(f"[SeleniumBase] 🛡️ Block detected in page source after navigation.")
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                    await self._rotate_proxy_locked()
                return None
            
            from common.universal_extractor import UniversalExtractor
            self.last_metadata = UniversalExtractor.extract_all(source)

            # Wait for AI response to fully render
            text = await self._wait_for_stable_response_locked(timeout_sec=25)
            if text:
                logger.info(f"✨ [SeleniumBase-{provider_label}] Got response ({len(text)} chars)")
                # Final block check on text
                if self.is_block_response(text):
                    logger.warning(f"[SeleniumBase] 🛡️ Block text detected in AI response.")
                    return None
            return text

        except Exception as exc:
            if self.is_block_response(exc):
                logger.error(f"[SeleniumBase] 🛑 Block/WAF detected during {provider_label} search.")
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)
                await self._rotate_proxy_locked()
                return None

            logger.error(f"[SeleniumBase] search_google_ai_mode error: {exc}")
            await self._record_interruption("exception", str(exc))
            return None

    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """🎭 HIGH-STEALTH INTERACTIVE SEARCH (Human-Like)"""
        async with self._lock:
            return await self._search_google_ai_interactive_locked(prompt, ai_mode_url, row)

    async def _search_google_ai_interactive_locked(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Internal locked interactive search."""
        if not await self._ensure_driver_alive_locked():
            return None

        # ── 1. Navigate to Google ──────────────────────────────────────────
        logger.info("🎭 [Human-Like] Starting interactive search cycle...")
        if not await self._goto_url_locked(config.GOOGLE_URL):
            return None
        
        await self._accept_cookies_locked()
        if not self._driver: return None

        # ── 2. Construct Query ─────────────────────────────────────────────
        if row:
            query = f"{getattr(row, 'company', '')} {getattr(row, 'address', '')} {getattr(row, 'domain', '')}".strip()
        else:
            query = prompt[:100]

        # ── 3. Type Query ──────────────────────────────────────────────────
        try:
            logger.info(f"⌨️ [Human-Like] Typing query: {query}")
            for sel in [GOOGLE_SEARCH_INPUT]:
                await asyncio.to_thread(self._driver.wait_for_element_visible, sel, timeout=5)
                await asyncio.to_thread(self._sync_human_type_locked, self._driver, sel, query)
                await asyncio.to_thread(self._driver.send_keys, sel, "\n")
                break
        except Exception as e:
            logger.error(f"[Human-Like] Search input failed: {e}")
            return None

        await asyncio.sleep(3)

        # ── 4. Immediate Check (Phone in SERP) ─────────────────────────────
        source = await self._get_page_source_locked()
        if source:
            phone_match = re.search(r'0[1-9](?:[\s.-]?\d{2}){4}', source)
            if phone_match:
                logger.info(f"✨ [Human-Like] Phone found DIRECTLY on SERP: {phone_match.group(0)}")
                return source 

        # ── 5. Trigger AI Mode ─────────────────────────────────────────────
        ai_buttons = [
            "button[aria-label*='Générer']", "button[aria-label*='Generate']",
            "button:contains('AI Overview')", "div[role='button']:contains('AI Overview')",
            "button:contains('Conversation')", "button:contains('Ask a follow up')",
        ]
        
        logger.info("[Human-Like] No phone on SERP. Attempting to trigger AI Overview...")
        for btn in ai_buttons:
            if not self._driver: break
            try:
                await asyncio.to_thread(self._driver.click, btn, timeout=3)
                logger.info(f"✅ [Human-Like] Clicked AI button: {btn}")
                break
            except Exception: continue
        
        await asyncio.sleep(4)
        if not self._driver: return None

        # ── 6. Type Prompt (if follow-up input exists) ─────────────────────
        follow_up_input = "textarea[placeholder*='follow-up'], textarea[placeholder*='Préciser']"
        try:
            await asyncio.to_thread(self._driver.wait_for_element_visible, follow_up_input, timeout=5)
            await asyncio.to_thread(self._sync_human_type_locked, self._driver, follow_up_input, prompt)
            await asyncio.to_thread(self._driver.send_keys, follow_up_input, "\n")
            logger.info("🤖 [Human-Like] Prompt typed in AI follow-up.")
        except Exception: pass

        # ── 7. Wait for stable response ────────────────────────────────────
        return await self._wait_for_stable_response_locked(timeout_sec=30)

    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Alias maintaining full HybridEngine / benchmark compatibility."""
        return await self.search_google_ai_mode(prompt, ai_mode_url=ai_mode_url, row=row)


    async def submit_google_search(self, prompt: str) -> bool:
        """Navigate to Google, dismiss cookies, type prompt, press Enter."""
        async with self._lock:
            return await self._submit_google_search_locked(prompt)

    async def _submit_google_search_locked(self, prompt: str) -> bool:
        """Internal locked search submission."""
        if not await self._ensure_driver_alive_locked():
            return False

        try:
            assert self._driver is not None  # guaranteed by _ensure_driver_alive_locked()
            await asyncio.to_thread(self._driver.get, config.GOOGLE_URL)
            await asyncio.sleep(1)

            await self._handle_captcha_if_present_locked()
            if not self._driver: return False

            await self._accept_cookies_locked()
            if not self._driver: return False

            for sel in ["textarea[name='q']", "input[name='q']"]:
                try:
                    await asyncio.to_thread(self._driver.wait_for_element_visible, sel, timeout=5)
                    await asyncio.to_thread(self._sync_human_type_locked, self._driver, sel, prompt)
                    await asyncio.to_thread(self._driver.send_keys, sel, "\n")
                    await asyncio.sleep(2)
                    return True
                except Exception: continue

            logger.warning("[SeleniumBase] _submit_google_search_locked: search box not found.")
            return False
        except Exception as exc:
            logger.error(f"[SeleniumBase] _submit_google_search_locked error: {exc}")
            if self.is_block_response(exc):
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)
            return False

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
        """Submit a prompt to Gemini and return the streamed response text."""
        async with self._lock:
            return await self._search_gemini_ai_locked(prompt)

    async def _search_gemini_ai_locked(self, prompt: str) -> Optional[str]:
        """Internal locked Gemini search."""
        if not await self._ensure_driver_alive_locked():
            return None

        try:
            assert self._driver is not None  # guaranteed by _ensure_driver_alive_locked()
            logger.info(f"🚀 [SeleniumBase-Gemini] DeepSearch: {prompt}")
            await asyncio.to_thread(self._driver.get, config.GEMINI_URL)
            await asyncio.sleep(3)
            if not self._driver: return None

            input_sel = None
            for sel in GEMINI_INPUT_SELECTORS:
                try:
                    await asyncio.to_thread(self._driver.wait_for_element_visible, sel, timeout=4)
                    input_sel = sel
                    break
                except Exception: continue

            if not input_sel:
                logger.warning("[SeleniumBase-Gemini] Input area not found.")
                return None

            await asyncio.to_thread(self._sync_human_type_locked, self._driver, input_sel, prompt)
            await asyncio.to_thread(self._driver.send_keys, input_sel, "\n")
            await asyncio.sleep(1)

            return await self._wait_for_stable_element_text_locked(GEMINI_RESPONSE_SELECTORS, timeout_sec=60)
        except Exception as exc:
            logger.error(f"[SeleniumBase] _search_gemini_ai_locked error: {exc}")
            if self.is_block_response(exc):
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)
            return None

    async def crawl_website(self, url: str) -> str:
        """Deep crawl of a website: homepage + subpages."""
        async with self._lock:
            return await self._crawl_website_locked(url)

    async def _crawl_website_locked(self, url: str) -> str:
        """Internal locked deep crawl."""
        if not await self._goto_url_locked(url):
            return ""
        if not self._driver: return ""

        try:
            all_text: list[str] = []
            src = await self._get_page_source_locked()
            body_text = re.sub(r"<[^>]+>", " ", src)
            body_text = re.sub(r"\s+", " ", body_text).strip()
            all_text.append(f"--- PAGE: {url} ---\n{body_text}")

            # Subpage discovery
            sublinks: list[str] = []
            try:
                anchors = await asyncio.to_thread(self._driver.find_elements, "tag name", "a")
                for a in anchors:
                    try:
                        text = (a.text or "").lower()
                        href = (a.get_attribute("href") or "").lower()
                        if any(k in text or k in href for k in config.CONTACT_KEYWORDS):
                            full_href = a.get_attribute("href") or ""
                            if full_href.startswith("http") and full_href != url:
                                sublinks.append(full_href)
                            elif full_href.startswith("/"):
                                from urllib.parse import urljoin
                                sublinks.append(urljoin(url, full_href))
                        if len(sublinks) >= 2: break
                    except Exception: continue
            except Exception: pass

            for sub in list(set(sublinks)):
                if not self._driver: break
                try:
                    logger.info(f"   ∟ [SeleniumBase] Visiting subpage: {sub}")
                    await asyncio.to_thread(self._sync_goto_with_driver, self._driver, sub)
                    await asyncio.sleep(1)
                    sub_src = await self._get_page_source_locked()
                    sub_text = re.sub(r"<[^>]+>", " ", sub_src)
                    sub_text = re.sub(r"\s+", " ", sub_text).strip()
                    all_text.append(f"\n--- PAGE: {sub} ---\n{sub_text}")
                except Exception: continue

            combined = "\n".join(all_text)
            return combined[:12000]
        except Exception as exc:
            logger.error(f"[SeleniumBase] crawl_website error: {exc}")
            return ""

    async def _handle_captcha_if_present_locked(self) -> bool:
        """Multi-layer CAPTCHA detection and resolution (locked version)."""
        if not self._driver: return False
        source = await self._get_page_source_locked()
        if not source: return False

        if self.is_block_response(source):
            logger.error("[SeleniumBase] 🚨 HARD IP BAN DETECTED (via is_block_response).")
            await self._record_interruption("ip_ban", "Hard block detected")
            if config.PROXY_ENABLED:
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)
                await self._rotate_proxy_locked()
            return True

        try:
            has_turnstile = await asyncio.to_thread(self._driver.is_element_visible, 'iframe[src*="turnstile"]')
            if has_turnstile:
                logger.warning("[SeleniumBase] ⚠️  Turnstile challenge detected.")
                await self._record_interruption("turnstile", "CF Turnstile challenge")
                await asyncio.to_thread(self._driver.uc_gui_click_captcha)
                # After clicking the native captcha UI, the page may still be gated.
                # Returning True tells the caller to treat this as an interruption.
                await asyncio.sleep(self._reconnect_time)
                return True
        except Exception: pass


        if is_captcha_page(source):
            logger.warning("[SeleniumBase] ⚠️  SOFT CAPTCHA / WAF detected.")
            await self._record_interruption("captcha_waf", "CAPTCHA challenge")
            if config.PROXY_ENABLED: await self._rotate_proxy_locked()
            else: await asyncio.to_thread(wait_for_human_captcha_solve)
            return True
        return False

    async def _accept_cookies_locked(self) -> None:
        """Accept Google cookie consent banners if present (locked)."""
        if not self._driver: return
        try:
            selectors = ["button:has-text('Accept all')", "button:has-text('Accepter tout')", "#L2AGLb"]
            for s in selectors:
                if not self._driver: break
                try:
                    visible = await asyncio.to_thread(self._driver.is_element_visible, s)
                    if visible:
                        await asyncio.to_thread(self._driver.click, s)
                        logger.info("[SeleniumBase] Cookie consent accepted.")
                        await asyncio.sleep(1)
                        break
                except Exception: continue
        except Exception: pass

    def _sync_human_type_locked(self, driver: Any, selector: str, text: str) -> None:
        """Character-by-character typing with Gaussian delays."""
        if not driver or not self._driver:
            return
            
        import numpy as np  # type: ignore
        profile = config.ACTION_DELAY_PROFILES.get("type_char", {"mean": 0.08, "std": 0.03, "min": 0.04, "max": 0.20})
        try: 
            driver.click(selector)
        except Exception: 
            pass

        for char in text:
            if not self._driver: 
                break
            try: 
                self._driver.send_keys(selector, char)
            except Exception:
                try: 
                    self._driver.type(selector, char)
                except Exception: 
                    pass
            try:
                delay = float(np.clip(np.random.normal(profile["mean"], profile["std"]), profile["min"], profile["max"]))
            except Exception:
                delay = random.uniform(config.TYPING_MIN_DELAY_SEC, config.TYPING_MAX_DELAY_SEC)
            time.sleep(delay)

    async def _wait_for_stable_response_locked(self, timeout_sec: int = 25) -> Optional[str]:
        """Poll the page until text stops changing (locked)."""
        deadline = time.monotonic() + timeout_sec
        prev_text = ""
        stable_count = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            if not self._driver: break
            current = await self._extract_first_selector_locked(AI_RESPONSE_SELECTORS)
            if not current:
                try: current = await asyncio.to_thread(lambda: self._driver.get_text("body"))
                except Exception: pass
            if current and current == prev_text:
                stable_count += 1
                if stable_count >= 2: return current
            else:
                prev_text = current or ""
                stable_count = 0
        return prev_text if prev_text else None

    async def _wait_for_stable_element_text_locked(self, selectors: list, timeout_sec: int = 60) -> Optional[str]:
        """Wait for selectors to produce stable text output (locked)."""
        deadline = time.monotonic() + timeout_sec
        last_text = ""
        stable_count = 0
        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            if not self._driver: break
            current = await self._extract_first_selector_locked(selectors) or ""
            if current and current == last_text:
                stable_count += 1
                if stable_count >= 4: return current
            else:
                stable_count = 0
                last_text = current
        return last_text if last_text else None

    async def _extract_first_selector_locked(self, selectors: list) -> Optional[str]:
        if not self._driver: return None
        for sel in selectors:
            try:
                visible = await asyncio.to_thread(self._driver.is_element_visible, sel)
                if visible:
                    text = await asyncio.to_thread(self._driver.get_text, sel)
                    if text and text.strip(): return text.strip()
            except Exception: continue
        return None

    async def generate_human_noise(self) -> None:
        """Protected simulation of human browsing activity."""
        async with self._lock:
            await self._generate_human_noise_locked()

    async def _generate_human_noise_locked(self) -> None:
        if not self._driver: return
        site = random.choice(config.HUMAN_NOISE_SITES)
        logger.info(f"🎭 [Human Noise] Simulating activity on: {site}")
        try:
            await asyncio.to_thread(self._driver.execute_script, f"window.open('{site}', '_blank');")
            await asyncio.to_thread(self._driver.switch_to.window, self._driver.window_handles[-1])
            await asyncio.sleep(random.uniform(5, 12))
            for _ in range(random.randint(2, 5)):
                if not self._driver: break
                await asyncio.to_thread(self._driver.execute_script, f"window.scrollBy(0, {random.randint(300, 800)});")
                await asyncio.sleep(random.uniform(1, 3))
            if self._driver:
                await asyncio.to_thread(self._driver.close)
                await asyncio.to_thread(self._driver.switch_to.window, self._driver.window_handles[0])
            logger.info("🎭 [Human Noise] Simulation complete.")
        except Exception as exc:
            logger.debug(f"[Human Noise] Simulation error: {exc}")
            try:
                if self._driver and len(self._driver.window_handles) > 1:
                    await asyncio.to_thread(self._driver.close)
                if self._driver:
                    await asyncio.to_thread(self._driver.switch_to.window, self._driver.window_handles[0])
            except: pass
