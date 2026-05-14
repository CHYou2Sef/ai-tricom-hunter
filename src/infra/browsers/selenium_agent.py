from __future__ import annotations
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
from typing import Optional, List, Dict, Any

from core import config
from agents.base_agent import BaseBrowserAgent
from common.anti_bot import get_fingerprint_bundle, is_captcha_page, wait_for_human_captcha_solve
from core.logger import get_logger, alert

logger = get_logger(__name__)

# ── Google selectors mirrored from patchright_agent.py ────────────────────
GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"], textarea[title="Search"], input[title="Search"], textarea[title="Rechercher"], input[title="Rechercher"], [aria-label="Search"]'
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
        self._lock = asyncio.Lock()
        self._last_health_check = 0.0
        self.current_proxy: Optional[str] = None
        self.last_interruption_reason: Optional[str] = None
        self.last_interruption_ts: Optional[float] = None

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch the Selenium browser with the requested stealth profile."""
        if self._driver:
            return

        logger.info(f"[Selenium] 🚀 Starting browser (worker={self.worker_id})...")
        
        # ── Proxy Configuration ──
        if not self.current_proxy and config.PROXY_ENABLED:
            from common.proxy_manager import get_next_proxy
            self.current_proxy = await get_next_proxy()

        try:
            await asyncio.to_thread(self._sync_start)
        except Exception as exc:
            # Record interruption in telemetry so it's captured by the benchmark runner
            await self._record_interruption("startup_failure", f"Failed to start: {exc}")
            # Log the specific error the user is looking for
            if "undetected_chromedriver" in str(exc) or "undetected-chromedriver" in str(exc):
                 logger.debug(f"[Selenium] undetected-chromedriver is not installed (expected in container).")
            raise

    def _sync_start(self) -> None:
        """Synchronous launch logic called via to_thread."""
        from pathlib import Path
        import time

        vp = self._fingerprint["viewport"]

        # ── Build common Chrome options ──
        common_args = [
            f"--window-size={vp['width']},{vp['height']}",
            "--lang=fr-FR",
            "--disable-notifications",
            "--no-sandbox",
            "--disable-dev-shm-usage",
        ]

        # Per-worker isolated profile
        profile_base = Path(config.CHROMIUM_PROFILE_PATH).parent
        profile_dir  = profile_base / f"selenium_worker_{self.worker_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        common_args.append(f"--user-data-dir={profile_dir}")

        # ── Proxy Configuration ──
        proxy = self.current_proxy
        if proxy:
            if "@" in proxy:
                # Proxy requires authentication (user:pass@host:port)
                from common.anti_bot import create_proxy_auth_extension
                ext_path = create_proxy_auth_extension(proxy, self.worker_id)
                if ext_path:
                    logger.info(f"[Selenium] 🔑 Using AUTH proxy with extension: {proxy}")
                    common_args.append(f"--load-extension={ext_path}")
            else:
                # Regular proxy
                logger.info(f"[Selenium] 🔌 Using proxy: {proxy}")
                common_args.append(f"--proxy-server={proxy}")

        # Headless mode config
        is_headless = (config.SELENIUM_DISPLAY_MODE == "headless")

        # ── Level 1: undetected-chromedriver (maximum stealth) ─────────────
        try:
            import undetected_chromedriver as uc  # type: ignore
            
            # Monkeypatch Patcher.data_path to avoid Read-Only file system errors
            import os
            uc_data_dir = os.environ.get("XDG_DATA_HOME", "/tmp/undetected_chromedriver")
            uc.patcher.Patcher.data_path = uc_data_dir
            if not os.path.exists(uc_data_dir):
                os.makedirs(uc_data_dir, exist_ok=True)

            options = uc.ChromeOptions()
            for arg in common_args:
                options.add_argument(arg)
            
            # Hardened: ensure path is a valid string or exactly None (not "")
            uc_path = config.CHROMIUM_BINARY_PATH if config.CHROMIUM_BINARY_PATH else None
            driver_path = None
            if uc_path:
                potential_driver = os.path.join(os.path.dirname(uc_path), "chromedriver")
                if os.path.exists(potential_driver):
                    driver_path = potential_driver

            self._driver = uc.Chrome(
                options=options,
                headless=is_headless,
                use_subprocess=True,
                version_main=None,
                browser_executable_path=uc_path,
                driver_executable_path=driver_path
            )
            self._stealth_mode = "undetected-chromedriver"
            logger.info(
                f"[Selenium] ✅ UC Mode — undetected-chromedriver started "
                f"({vp['width']}×{vp['height']}, worker={self.worker_id}, headless={is_headless})"
            )

        # ── Level 2: plain selenium.webdriver.Chrome with stealth flags ────
        except (ImportError, Exception) as uc_exc:
            logger.warning(
                f"[Selenium] undetected-chromedriver skipped ({uc_exc}) — "
                "falling back to standard selenium (stealth flags active)"
            )
            try:
                from selenium import webdriver  # type: ignore
                from selenium.webdriver.chrome.service import Service
                from selenium.webdriver.chrome.options import Options

                options = Options()
                for arg in common_args:
                    options.add_argument(arg)
                
                if config.SELENIUM_DISPLAY_MODE == "headless":
                    options.add_argument("--headless=new")

                # Try local installation first, then download if needed
                try:
                    service = Service()
                    self._driver = webdriver.Chrome(service=service, options=options)
                except Exception:
                    from webdriver_manager.chrome import ChromeDriverManager
                    service = Service(ChromeDriverManager().install())
                    self._driver = webdriver.Chrome(service=service, options=options)

                # ── Post-launch stealth: Full CDP Fingerprint Injection ─────
                # We use the shared script from anti_bot.py to mask all 10+ signals
                from common.anti_bot import build_cdp_injection_script
                fp_script = build_cdp_injection_script(self._fingerprint)
                self._driver.execute_cdp_cmd(
                    "Page.addScriptToEvaluateOnNewDocument",
                    {"source": fp_script}
                )
                
                self._stealth_mode = "selenium-stealth-bundle"
                logger.info(
                    f"[Selenium] ✅ Fallback Mode — selenium started with stealth bundle "
                    f"({vp['width']}×{vp['height']})"
                )
            except Exception as exc:
                msg = f"Neither undetected-chromedriver nor selenium could start: {exc}. Run: pip install selenium undetected-chromedriver"
                raise ImportError(msg) from exc

        self._driver.set_page_load_timeout(30)
        self._driver.implicitly_wait(5)
        self._session_start_ts = time.monotonic()
    async def is_alive(self) -> bool:
        """Public health check with lock protection."""
        async with self._lock:
            if not self._driver: return False
            try:
                # Use execute_script for a robust liveness check
                await asyncio.to_thread(self._driver.execute_script, "return 1+1")
                return True
            except Exception:
                return False

    async def _ensure_driver_alive_locked(self) -> bool:
        """
        Heartbeat check for the Selenium driver.
        Restarts if dead or None.
        """
        now = time.time()
        if self._driver and (now - self._last_health_check) < 5:
            return True

        if not self._driver:
            logger.info("[Selenium] 🔄 Driver missing. Restarting...")
            await self._start_locked()
            return self._driver is not None

        try:
            # Heartbeat check
            await asyncio.to_thread(self._driver.execute_script, "return 1+1")
            self._last_health_check = now
            return True
        except Exception as e:
            logger.warning(f"[Selenium] 💔 Driver unresponsive: {e}. Resurrecting...")
            await self._close_locked()
            await self._start_locked()
            return self._driver is not None

    async def _start_locked(self) -> None:
        """Internal lock-free start."""
        if self._driver: return
        try:
            await asyncio.to_thread(self._sync_start)
            self._last_health_check = time.time()
        except Exception as exc:
            await self._record_interruption("startup_failure", f"Failed to start: {exc}")
            raise

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
        await asyncio.to_thread(self._sync_close)
        self._driver = None

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
        """Fetch a new proxy and restart the browser session."""
        from common.proxy_manager import get_next_proxy
        new_proxy = await get_next_proxy()
        
        if new_proxy:
            logger.info(f"[Selenium-Worker-{self.worker_id}] ♻️  Rotating proxy to: {new_proxy}")
            await self.close()
            self._clear_profile()
            self.current_proxy = new_proxy
            await self.start()
        else:
            logger.warning(f"[Selenium-Worker-{self.worker_id}] No proxies left for rotation.")

    def _clear_profile(self) -> None:
        """Delete the current profile directory to clear 'corrupted' CAPTCHA session state."""
        import shutil
        from pathlib import Path
        p = Path(config.CHROMIUM_PROFILE_PATH).parent / f"selenium_worker_{self.worker_id}"
        if p.exists():
            try:
                shutil.rmtree(p)
                logger.info(f"[Selenium] 🧹 Profile cleared at {p}")
            except Exception as e:
                logger.debug(f"[Selenium] Could not clear profile: {e}")

    def _create_proxy_auth_extension(self, proxy_url: str) -> Optional[str]:
        """
        Creates a temporary Chrome extension to handle proxy authentication
        (bypasses the native 'Sign In' popup).
        """
        import zipfile
        try:
            # Parse proxy_url: http://user:pass@host:port
            auth_part, host_port = proxy_url.split("@")
            username, password = auth_part.replace("http://", "").replace("https://", "").split(":")
            host, port = host_port.split(":")

            manifest_json = """
            {
                "version": "1.0.0",
                "manifest_version": 2,
                "name": "Chrome Proxy",
                "permissions": [
                    "proxy",
                    "tabs",
                    "unlimitedStorage",
                    "storage",
                    "<all_urls>",
                    "webRequest",
                    "webRequestBlocking"
                ],
                "background": {
                    "scripts": ["background.js"]
                },
                "minimum_chrome_version":"22.0.0"
            }
            """

            background_js = """
            var config = {
                mode: "fixed_servers",
                rules: {
                  singleProxy: {
                    scheme: "http",
                    host: "%(host)s",
                    port: parseInt(%(port)s)
                  },
                  bypassList: ["localhost"]
                }
              };

            chrome.proxy.settings.set({value: config, scope: "regular"}, function() {});

            function callbackFn(details) {
                return {
                    authCredentials: {
                        username: "%(username)s",
                        password: "%(password)s"
                    }
                };
            }

            chrome.webRequest.onAuthRequired.addListener(
                    callbackFn,
                    {urls: ["<all_urls>"]},
                    ['blocking']
            );
            """ % {
                "host": host,
                "port": port,
                "username": username,
                "password": password,
            }

            ext_base = Path(config.BASE_DIR) / "WORK" / "extensions"
            ext_base.mkdir(parents=True, exist_ok=True)
            plugin_path = ext_base / f"proxy_auth_{self.worker_id}.zip"

            with zipfile.ZipFile(plugin_path, 'w') as zp:
                zp.writestr("manifest.json", manifest_json)
                zp.writestr("background.js", background_js)

            self._proxy_ext_path = str(plugin_path)
            return self._proxy_ext_path
        except Exception as e:
            logger.error(f"[Selenium] Failed to create proxy auth extension: {e}")
            return None

    # ── Core interface ─────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return the raw HTML of the current page."""
        async with self._lock:
            if not await self._ensure_driver_alive_locked():
                return ""
            try:
                return await asyncio.to_thread(lambda: self._driver.page_source)
            except Exception:
                return ""

    async def goto_url(self, url: str) -> bool:
        """Navigate to an arbitrary URL."""
        async with self._lock:
            if not await self._ensure_driver_alive_locked():
                return False
            try:
                logger.info(f"[Selenium] Navigating to: {url}")
                await asyncio.to_thread(self._driver.get, url)
                
                # Check for blocks immediately after navigation
                if await self._handle_captcha_if_present_locked():
                    return False
                    
                return True
            except Exception as exc:
                if self.is_block_response(exc):
                    logger.error(f"[Selenium] 🛑 Session/Proxy FAILED (Block detected). Reporting...")
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                    await self.rotate_proxy()
                    return False
                logger.error(f"[Selenium] goto_url error: {exc}")
                return False

    # ── Search methods ─────────────────────────────────────────────────────

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """
        PRIMARY SEARCH — direct navigation to Google AI Mode URL.
        """
        async with self._lock:
            if not await self._ensure_driver_alive_locked():
                return None
            
            if ai_mode_url:
                import urllib.parse
                from common.search_engine import extract_search_terms
                clean_query = extract_search_terms(prompt)
                url = ai_mode_url + urllib.parse.quote_plus(clean_query)
            else:
                from common.search_engine import generate_google_ai_url
                url = generate_google_ai_url(prompt)

            try:
                logger.info(f"🤖 [Selenium-AI-Mode] Navigating for prompt ({len(prompt)} chars)")
                await asyncio.to_thread(self._driver.get, url)
                
                # Check for blocks
                if await self._handle_captcha_if_present_locked():
                    return None

                # Wait for AI response to stabilise
                text = await self._wait_for_stable_response(timeout_sec=20)
                if text:
                    logger.info(f"✨ [Selenium-AI-Mode] Got response ({len(text)} chars)")
                    if self.is_block_response(text):
                        logger.warning("[Selenium] 🛡️ Block detected in AI response text.")
                        return None
                return text

            except Exception as exc:
                if self.is_block_response(exc):
                    logger.error(f"[Selenium] 🛑 Block/WAF detected during AI search. Reporting...")
                    if self.current_proxy:
                        await self.report_proxy_error(self.current_proxy, 403)
                    await self.rotate_proxy()
                    return None
                
                logger.error(f"[Selenium] search_google_ai_mode error: {exc}")
                await self._record_interruption("exception", str(exc))
                return None

    async def submit_google_search(self, prompt: str) -> bool:
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

            await self._human_type(box, prompt)
            await asyncio.to_thread(box.submit)
            await asyncio.sleep(2)
            return True

        except Exception as exc:
            logger.error(f"[Selenium] submit_google_search error: {exc}")
            return False

    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Alias maintaining full HybridEngine / benchmark compatibility."""
        return await self.search_google_ai_mode(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """
        Interactive high-stealth search flow.
        """
        # For now, we fallback to the mode navigation as Selenium UC is already stealthy
        return await self.search_google_ai_mode(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
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

            await self._human_type(box, prompt)
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

    async def _handle_captcha_if_present_locked(self) -> bool:
        """
        Refined detection for CAPTCHA vs IP Ban / Hard Block.
        Returns True if the session is blocked and needs rotation/escalation.
        """
        source = await self.get_page_source()
        if not source:
            return False

        if self.is_block_response(source):
            logger.error("[Selenium] 🚨 HARD IP BAN DETECTED.")
            await self._record_interruption("ip_ban", "Hard block (Access Denied / 403)")
            if config.PROXY_ENABLED:
                if self.current_proxy:
                    await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
            return True

        if is_captcha_page(source):
            logger.warning("[Selenium] ⚠️  SOFT CAPTCHA / WAF Detected (Unusual Traffic).")
            await self._record_interruption("captcha_waf", "CAPTCHA challenge detected")
            
            if config.PROXY_ENABLED:
                logger.info("[Selenium] ♻️  Attempting automated proxy rotation for CAPTCHA...")
                await self.rotate_proxy()
            else:
                await asyncio.to_thread(wait_for_human_captcha_solve)
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
