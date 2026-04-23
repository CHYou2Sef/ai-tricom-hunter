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

from core import config
from agents.base_agent import BaseBrowserAgent
from common.anti_bot import get_fingerprint_bundle, is_captcha_page, wait_for_human_captcha_solve
from core.logger import get_logger, alert

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
        """Launch the Selenium browser with the requested stealth profile."""
        if self._driver:
            return

        logger.info(f"[Selenium] 🚀 Starting browser (worker={self.worker_id})...")
        try:
            await asyncio.to_thread(self._sync_start)
        except Exception as exc:
            # Record interruption in telemetry so it's captured by the benchmark runner
            await self._record_interruption("startup_failure", f"Failed to start: {exc}")
            # Log the specific error the user is looking for
            if "undetected_chromedriver" in str(exc) or "undetected-chromedriver" in str(exc):
                 logger.error(f"[Selenium] ❌ undetected-chromedriver is not installed. Run: pip install undetected-chromedriver")
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
        ]

        # Per-worker isolated profile
        profile_base = Path(config.CHROMIUM_PROFILE_PATH).parent
        profile_dir  = profile_base / f"selenium_worker_{self.worker_id}"
        profile_dir.mkdir(parents=True, exist_ok=True)
        common_args.append(f"--user-data-dir={profile_dir}")

        # ── Proxy Configuration ──
        import os
        from common.anti_bot import create_proxy_auth_extension
        proxy = os.getenv("PROXY") or getattr(config, "PROXY_DEFAULT", None)
        if proxy:
            if "@" in proxy:
                # Proxy requires authentication (user:pass@host:port)
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
            options = uc.ChromeOptions()
            for arg in common_args:
                options.add_argument(arg)
            
            # Hardened: ensure path is a valid string or exactly None (not "")
            uc_path = config.CHROMIUM_BINARY_PATH if config.CHROMIUM_BINARY_PATH else None

            self._driver = uc.Chrome(
                options=options,
                headless=is_headless,
                use_subprocess=True,
                version_main=None,
                browser_executable_path=uc_path
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
        new_proxy = get_next_proxy()
        
        if new_proxy:
            logger.info(f"[Selenium-Worker-{self.worker_id}] ♻️  Rotating proxy to: {new_proxy}")
            # To fix 'corruption', we also clear the profile directory
            await self.close()
            self._clear_profile()
            import os
            os.environ["PROXY"] = new_proxy # Update for sync-started driver
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
            msg = str(exc)
            if any(err in msg for err in ["ERR_TUNNEL_CONNECTION_FAILED", "ERR_PROXY_CONNECTION_FAILED", "invalid session id"]):
                logger.error(f"[Selenium] 🛑 Session/Proxy FAILED (Self-Healing triggered). Rotating...")
                await self.rotate_proxy()
                # Retry once after rotation
                try:
                    await asyncio.to_thread(self._driver.get, url)
                    return True
                except:
                    return False
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
        
        from common.search_engine import generate_google_ai_url
        url = generate_google_ai_url(prompt)

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
            msg = str(exc).lower()
            if any(err in msg for err in ["err_tunnel_connection_failed", "err_proxy_connection_failed", "invalid session id"]):
                logger.error(f"[Selenium] 🛑 Session/Proxy FAILED during AI search. Self-healing...")
                await self.rotate_proxy()
                # Recurse once with new proxy/session
                return await self.search_google_ai_mode(prompt)
            
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
        Refined detection for CAPTCHA vs IP Ban / Hard Block.
        Returns True if the session is blocked and needs rotation/escalation.
        """
        source = await self.get_page_source()
        if not source:
            return False

        lower_source = source.lower()
        
        # 1. Detect Hard IP Ban (403/429/Access Denied)
        hard_ban_keywords = ["access denied", "forbidden", "too many requests", "403 forbidden", "429 too many"]
        if any(kw in lower_source for kw in hard_ban_keywords):
            logger.error("[Selenium] 🚨 HARD IP BAN DETECTED.")
            await self._record_interruption("ip_ban", "Hard block (Access Denied / 403)")
            if config.PROXY_ENABLED:
                await self.rotate_proxy()
            return True

        # 2. Detect Soft CAPTCHA / Unusual Traffic
        if is_captcha_page(source):
            logger.warning("[Selenium] ⚠️  SOFT CAPTCHA / WAF Detected (Unusual Traffic).")
            await self._record_interruption("captcha_waf", "CAPTCHA challenge detected")
            
            # Fast solution: If we hit unusual traffic, rotation is usually the only way out
            # without manual intervention.
            if config.PROXY_ENABLED:
                logger.info("[Selenium] ♻️  Attempting automated proxy rotation for CAPTCHA...")
                await self.rotate_proxy()
            else:
                # Fallback to manual solve if no proxies
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
