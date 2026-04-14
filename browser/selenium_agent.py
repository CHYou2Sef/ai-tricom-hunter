"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/selenium_agent.py                                               ║
║                                                                          ║
║  BENCHMARK ENGINE — Selenium 4 + Undetected-ChromeDriver                 ║
║                                                                          ║
║  This agent implements the full BaseBrowserAgent contract for use in     ║
║  both the standalone benchmark runner AND (optionally) the HybridEngine. ║
║                                                                          ║
║  Anti-detection strategy:                                                ║
║    ✓ undetected-chromedriver (UC mode) — zero WebDriver flag             ║
║    ✓ Randomised viewport + User-Agent per session                        ║
║    ✓ Human-like typing delays between every keystroke                    ║
║    ✓ Integrated CAPTCHA/IP-ban interruption signaling for MTTI tracking  ║
║    ✓ Graceful teardown — always kills chromedriver subprocess            ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import random
import re
import time
import urllib.parse
from pathlib import Path
from typing import Optional

import config
from agents.base_agent import BaseBrowserAgent
from utils.anti_bot import get_fingerprint_bundle, is_captcha_page
from utils.logger import get_logger, alert

logger = get_logger(__name__)

# ── Google selectors mirrored from patchright_agent.py ────────────────────
GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"]'
GOOGLE_PHONE_SELECTORS = [
    "[data-attrid='kc:/local:phone'] span",
    "[data-attrid='tel'] span",
    "[data-dtype='d3ph'] span",
    ".LGOjhe span",
    ".zS8pY",
    "span[data-dtype='d3ph']",
    ".kno-rdesc span",
    ".yDYNvb.lyLwlc",
]


class SeleniumAgent(BaseBrowserAgent):
    """
    Benchmark browser agent built on Selenium 4 + undetected-chromedriver.

    Implements the full BaseBrowserAgent interface so it can be hot-swapped
    with any other tier without modifying calling code.

    Lifecycle:
        agent = SeleniumAgent()
        await agent.start()
        try:
            result = await agent.search_google_ai_mode(prompt)
        finally:
            await agent.close()
    """

    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._driver = None
        self._session_start_ts: float = 0.0
        self._fingerprint = get_fingerprint_bundle()
        # Interruption metadata — read by BenchmarkTelemetry
        self.last_interruption_reason: Optional[str] = None
        self.last_interruption_ts: Optional[float] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Launch an undetected-chromedriver session.
        All browser I/O is synchronous internally; we run it in a
        thread pool so the asyncio event loop stays unblocked.
        """
        await asyncio.to_thread(self._sync_start)

    def _sync_start(self) -> None:
        try:
            import undetected_chromedriver as uc  # type: ignore
        except ImportError:
            raise RuntimeError(
                "undetected-chromedriver is not installed.\n"
                "Run: pip install undetected-chromedriver"
            )

        vp = self._fingerprint["viewport"]
        options = uc.ChromeOptions()
        options.add_argument(f"--window-size={vp['width']},{vp['height']}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--no-first-run")
        options.add_argument("--no-default-browser-check")
        options.add_argument("--disable-infobars")
        options.add_argument(f"--lang=fr-FR")

        if not config.BROWSER_USE_SANDBOX:
            options.add_argument("--no-sandbox")
            options.add_argument("--disable-setuid-sandbox")

        # Use a per-worker profile directory to avoid lock conflicts
        profile_base = Path(config.CHROMIUM_PROFILE_PATH).parent
        profile_dir  = profile_base / f"selenium_worker_{self.worker_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={profile_dir}")

        self._driver = uc.Chrome(
            options=options,
            headless=False,
            use_subprocess=True,
            version_main=None,  # auto-detect
        )
        self._driver.set_page_load_timeout(30)
        self._driver.implicitly_wait(5)
        self._session_start_ts = time.monotonic()

        logger.info(
            f"[Selenium] ✅ Ready — undetected-chromedriver started "
            f"({vp['width']}×{vp['height']}, worker={self.worker_id})"
        )

    async def close(self) -> None:
        """Terminate the ChromeDriver subprocess and release all handles."""
        await asyncio.to_thread(self._sync_close)

    def _sync_close(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            finally:
                self._driver = None
        logger.info("[Selenium] Browser closed.")

    async def rotate_proxy(self) -> None:
        """Proxy rotation: restart the session with the new proxy in the env."""
        logger.info(f"[Selenium-Worker-{self.worker_id}] ♻️ Rotating proxy — restarting session.")
        await self.close()
        await self.start()

    # ── Core interface ─────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return the raw HTML of the current page."""
        if not self._driver:
            return ""
        try:
            return await asyncio.to_thread(lambda: self._driver.page_source)
        except Exception:
            return ""

    async def goto_url(self, url: str) -> bool:
        """Navigate to an arbitrary URL."""
        if not self._driver:
            return False
        try:
            await asyncio.to_thread(self._driver.get, url)
            await self._handle_captcha_if_present()
            return True
        except Exception as exc:
            logger.error(f"[Selenium] goto_url error: {exc}")
            return False

    # ── Search methods ─────────────────────────────────────────────────────

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """
        PRIMARY SEARCH — direct navigation to Google AI Mode URL.
        Returns the page text for downstream JSON/regex extraction.
        """
        if not self._driver:
            return None

        encoded = urllib.parse.quote_plus(prompt)
        url = config.GOOGLE_AI_MODE_URL + encoded

        try:
            logger.info(f"🤖 [Selenium-AI-Mode] Navigating for prompt ({len(prompt)} chars)")
            await asyncio.to_thread(self._driver.get, url)
            await asyncio.sleep(2.5)

            interrupted = await self._handle_captcha_if_present()
            if interrupted:
                return None

            # Wait for AI response to stabilise
            text = await self._wait_for_stable_response(timeout_sec=20)
            if text:
                logger.info(f"✨ [Selenium-AI-Mode] Got response ({len(text)} chars)")
            return text

        except Exception as exc:
            logger.error(f"[Selenium] search_google_ai_mode error: {exc}")
            await self._record_interruption("exception", str(exc))
            return None

    async def submit_google_search(self, query: str) -> bool:
        """Navigate to Google, submit a search query, return True on success."""
        if not self._driver:
            return False
        try:
            await asyncio.to_thread(self._driver.get, config.GOOGLE_URL)
            await asyncio.sleep(1)

            interrupted = await self._handle_captcha_if_present()
            if interrupted:
                return False

            await self._accept_cookies()
            box = await self._find_element_by_css(GOOGLE_SEARCH_INPUT)
            if not box:
                return False

            await self._human_type(box, query)
            await asyncio.to_thread(box.submit)
            await asyncio.sleep(2)
            return True

        except Exception as exc:
            logger.error(f"[Selenium] submit_google_search error: {exc}")
            return False

    async def search_google_ai(self, query: str) -> Optional[str]:
        """Alias maintaining full HybridEngine / benchmark compatibility."""
        return await self.search_google_ai_mode(query)

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        """Submit a query to Gemini and return response text."""
        if not self._driver:
            return None
        try:
            await asyncio.to_thread(self._driver.get, config.GEMINI_URL)
            await asyncio.sleep(3)

            input_sel = "div[role='combobox'], .ql-editor, textarea"
            box = await self._find_element_by_css(input_sel)
            if not box:
                return None

            await self._human_type(box, query)
            await asyncio.to_thread(box.send_keys, "\n")
            await asyncio.sleep(5)
            return await self.get_page_source()

        except Exception as exc:
            logger.error(f"[Selenium] search_gemini_ai error: {exc}")
            return None

    async def crawl_website(self, url: str) -> str:
        """Visit a URL and return all visible page text (capped at 8k chars)."""
        if not await self.goto_url(url):
            return ""
        try:
            source = await self.get_page_source()
            text = re.sub(r"<[^>]+>", " ", source)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:8000]
        except Exception as exc:
            logger.error(f"[Selenium] crawl_website error: {exc}")
            return ""

    # ── CAPTCHA & interruption handling ────────────────────────────────────

    async def _handle_captcha_if_present(self) -> bool:
        """
        Detect WAF blocks, IP bans, or CAPTCHA challenges.
        Records the interruption event for MTTI telemetry.
        Returns True if the session is interrupted, False if page is clean.
        """
        source = await self.get_page_source()
        if not source:
            return False

        if is_captcha_page(source):
            logger.warning("[Selenium] ⚠️  CAPTCHA / WAF block detected.")
            await self._record_interruption("captcha_waf", "CAPTCHA page detected")
            await asyncio.sleep(10)  # Short non-blocking pause → let waterfall escalate
            return True

        # Heuristic: IP ban pages often have very short body content
        if len(source) < 1000 and any(
            kw in source.lower() for kw in ["unusual traffic", "ip banned", "access denied", "403", "429"]
        ):
            logger.warning("[Selenium] ⚠️  Likely IP restriction / rate-limit page.")
            await self._record_interruption("ip_ban", "Rate-limit / 403 / 429 detected")
            return True

        return False

    async def _record_interruption(self, reason: str, detail: str) -> None:
        """Record the timestamp and reason of an interruption for MTTI tracking."""
        self.last_interruption_reason = reason
        self.last_interruption_ts = time.monotonic()
        alert(
            "WARNING",
            f"[Selenium] Session interrupted: {reason}",
            {"detail": detail, "worker": self.worker_id},
        )

    # ── Private helpers ────────────────────────────────────────────────────

    async def _accept_cookies(self) -> None:
        """Dismiss Google cookie consent if present."""
        try:
            from selenium.webdriver.common.by import By
            selectors = ["button#L2AGLb", "button#W0wltc"]
            for sel in selectors:
                elements = await asyncio.to_thread(
                    self._driver.find_elements, By.CSS_SELECTOR, sel
                )
                if elements and elements[0].is_displayed():
                    await asyncio.to_thread(elements[0].click)
                    await asyncio.sleep(0.8)
                    break
        except Exception:
            pass

    async def _find_element_by_css(self, selector: str):
        """Return the first visible element matching a CSS selector, or None."""
        if not self._driver:
            return None
        try:
            from selenium.webdriver.common.by import By
            elements = await asyncio.to_thread(
                self._driver.find_elements, By.CSS_SELECTOR, selector
            )
            for el in elements:
                if await asyncio.to_thread(lambda e=el: e.is_displayed()):
                    return el
        except Exception:
            pass
        return None

    async def _human_type(self, element, text: str) -> None:
        """Type text character-by-character with random human-like delays."""
        for char in text:
            await asyncio.to_thread(element.send_keys, char)
            await asyncio.sleep(random.uniform(
                config.TYPING_MIN_DELAY_SEC,
                config.TYPING_MAX_DELAY_SEC,
            ))

    async def _wait_for_stable_response(self, timeout_sec: int = 20) -> Optional[str]:
        """
        Poll the page every 1.5s until the body text stops changing.
        Returns the stable text or whatever was last seen.
        """
        deadline = time.monotonic() + timeout_sec
        prev = ""
        stable_count = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)
            try:
                current = await asyncio.to_thread(
                    lambda: self._driver.find_element(
                        __import__("selenium").webdriver.common.by.By.TAG_NAME, "body"
                    ).text
                )
            except Exception:
                break

            if current and current == prev:
                stable_count += 1
                if stable_count >= 2:
                    return current
            else:
                prev = current
                stable_count = 0

        return prev or None
