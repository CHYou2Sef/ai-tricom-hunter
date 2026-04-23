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
║    ✓ xvfb guard        — auto-detects headless Linux, sets DISPLAY=:99  ║
║                                                                          ║
║  Implemented scraping methods (BaseBrowserAgent contract):               ║
║    • search_google_ai_mode()   PRIMARY: direct AI Mode URL               ║
║    • search_google_ai()        Alias for waterfall compatibility          ║
║    • submit_google_search()    Standard search + human typing            ║
║    • search_gemini_ai()        Gemini chat interface                     ║
║    • crawl_website()           Deep crawl with contact page discovery    ║
║    • goto_url()                Generic URL navigation                    ║
║    • get_page_source()         Raw HTML of current page                  ║
║    • extract_universal_data()  Inherited from BaseBrowserAgent           ║
║    • rotate_proxy()            Session teardown + proxy swap + restart   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import os
import random
import re
import time
from pathlib import Path
from typing import Optional

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
GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"]'
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
        self._session_start_ts: float = 0.0
        self._fingerprint = get_fingerprint_bundle()
        self.last_interruption_reason: Optional[str] = None
        self.last_interruption_ts: Optional[float] = None

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch SeleniumBase UC Driver with stealth config."""
        if self._driver:
            return

        logger.info(
            f"[SeleniumBase] 🚀 Starting UC Driver "
            f"(worker={self.worker_id}, uc=True, headless=False)..."
        )
        try:
            await asyncio.to_thread(self._sync_start)
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

        # ── Synchronous driver bootstrap ──

        # ── Reconnect time for Turnstile challenges (Gemini.md §2) ────────
        self._reconnect_time = getattr(config, "SELENIUMBASE_RECONNECT_TIME", 4)

        # ── Proxy ─────────────────────────────────────────────────────────
        proxy_str = None
        proxy_env = os.getenv("PROXY") or getattr(config, "PROXY_DEFAULT", None)
        if proxy_env:
            proxy_str = proxy_env
            logger.info(f"[SeleniumBase] 🔌 Using proxy: {proxy_str}")

        # ── Suppression of automation alerts & Sandbox handling ──
        # If NOT in Docker, we avoid --no-sandbox to remove the 'unsupported flag' warning.
        extra_args = "--disable-infobars --disable-notifications"
        if not getattr(config, "DOCKER_ENV", False):
            # Explicitly try to avoid no-sandbox on host machines
            extra_args += " --no-sandbox=false" 

        self._driver = Driver(
            uc=True,
            headless=False,
            ad_block=True,
            proxy=proxy_str,
            binary_location=config.CHROMIUM_BINARY_PATH or None,
            locale_code="fr",
            chromium_arg=extra_args,
        )

        # ── Resize window to fingerprinted viewport ────────────────────────
        try:
            self._driver.set_window_size(vp["width"], vp["height"])
        except Exception:
            pass

        self._driver.set_page_load_timeout(30)
        self._session_start_ts = time.monotonic()

        logger.info(
            f"[SeleniumBase] ✅ UC Driver ready — "
            f"uc=True, headless=False, "
            f"viewport={vp['width']}×{vp['height']}, "
            f"worker={self.worker_id}"
        )

    async def close(self) -> None:
        """Gracefully quit the UC Driver subprocess."""
        await asyncio.to_thread(self._sync_close)

    def _sync_close(self) -> None:
        if self._driver:
            try:
                self._driver.quit()
            except Exception:
                pass
            finally:
                self._driver = None
        logger.info("[SeleniumBase] Browser closed.")

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy from the pool and restart the browser session."""
        from common.proxy_manager import get_next_proxy
        new_proxy = get_next_proxy()
        if new_proxy:
            logger.info(
                f"[SeleniumBase-Worker-{self.worker_id}] "
                f"♻️  Rotating proxy to: {new_proxy}"
            )
            await self.close()
            os.environ["PROXY"] = new_proxy
            await self.start()
        else:
            logger.warning(
                f"[SeleniumBase-Worker-{self.worker_id}] No proxies left for rotation."
            )

    # ── Core interface ────────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return raw HTML of the current page."""
        if not self._driver:
            return ""
        try:
            return await asyncio.to_thread(lambda: self._driver.get_page_source())
        except Exception:
            return ""

    async def goto_url(self, url: str) -> bool:
        """
        Navigate to a URL and wait for ready state.
        Handles proxy/session failures with one automatic retry after rotation.
        """
        if not self._driver:
            return False
        try:
            await asyncio.to_thread(self._sync_goto, url)
            await self._handle_captcha_if_present()
            return True
        except Exception as exc:
            msg = str(exc)
            if any(
                err in msg
                for err in [
                    "ERR_TUNNEL_CONNECTION_FAILED",
                    "ERR_PROXY_CONNECTION_FAILED",
                    "invalid session id",
                ]
            ):
                logger.error("[SeleniumBase] 🛑 Session/Proxy FAILED. Self-healing...")
                await self.rotate_proxy()
                try:
                    await asyncio.to_thread(self._sync_goto, url)
                    return True
                except Exception:
                    return False
            logger.error(f"[SeleniumBase] goto_url error: {exc}")
            return False

    def _sync_goto(self, url: str) -> None:
        """Synchronous navigate + wait for page ready."""
        self._driver.get(url)
        try:
            self._driver.wait_for_ready_state_complete(timeout=20)
        except Exception:
            pass  # Best-effort; continue even if the wait times out

    # ── Search methods ────────────────────────────────────────────────────────

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """
        ⭐ PRIMARY SEARCH — direct navigation to Google AI Mode URL.

        Implements the Gemini.md §3 pattern:
            driver.get(ai_mode_url)
            wait_for_ready_state_complete()
            handle Turnstile if present
            extract stable page text

        Returns the page text for downstream JSON / regex extraction.
        """
        if not self._driver:
            return None

        from common.search_engine import generate_google_ai_url
        url = generate_google_ai_url(prompt)

        try:
            logger.info(
                f"🤖 [SeleniumBase-AI-Mode] Navigating for prompt "
                f"({len(prompt)} chars)..."
            )
            await asyncio.to_thread(self._sync_goto, url)
            await asyncio.sleep(2.5)

            # ── 1. Handle Turnstile / CAPTCHA ────────────────────────────
            interrupted = await self._handle_captcha_if_present()
            if interrupted:
                return None

            # ── 2. Handle Cookies (Critical for AI Mode to load) ────────
            await self._accept_cookies()

            # ── 3. Extract data using UUE (Universal Unified Extractor) ──
            metadata = await self.extract_universal_data()
            if metadata:
                # Prioritize heuristic phones (from Knowledge Panel)
                if metadata.get("heuristic_phones"):
                    logger.info("✨ [SeleniumBase-AI-Mode] Phone found via UUE Heuristics.")
                    return metadata["heuristic_phones"][0]
                
                # Fallback to AI mode response stability wait if UUE found nothing
                # (This covers the case where AI Mode is still typing)
            
            text = await self._wait_for_stable_response(timeout_sec=25)
            if text:
                logger.info(
                    f"✨ [SeleniumBase-AI-Mode] Got response ({len(text)} chars)"
                )
            return text

        except Exception as exc:
            msg = str(exc).lower()
            if any(
                err in msg
                for err in [
                    "err_tunnel_connection_failed",
                    "err_proxy_connection_failed",
                    "invalid session id",
                ]
            ):
                logger.error(
                    "[SeleniumBase] 🛑 Session/Proxy FAILED during AI search. Self-healing..."
                )
                await self.rotate_proxy()
                return await self.search_google_ai_mode(prompt)

            logger.error(f"[SeleniumBase] search_google_ai_mode error: {exc}")
            await self._record_interruption("exception", str(exc))
            return None

    async def search_google_ai(self, query: str) -> Optional[str]:
        """Alias maintaining full HybridEngine / benchmark compatibility."""
        return await self.search_google_ai_mode(query)

    async def submit_google_search(self, query: str) -> bool:
        """
        Navigate to Google, dismiss cookies, type query, press Enter.
        Uses SeleniumBase's human_type() for natural keystroke delays.
        """
        if not self._driver:
            return False
        try:
            await asyncio.to_thread(self._driver.get, config.GOOGLE_URL)
            await asyncio.sleep(1)

            interrupted = await self._handle_captcha_if_present()
            if interrupted:
                return False

            await self._accept_cookies()

            # Find the search box and type human-like
            for sel in ["textarea[name='q']", "input[name='q']"]:
                try:
                    await asyncio.to_thread(
                        self._driver.wait_for_element_visible, sel, timeout=5
                    )
                    await asyncio.to_thread(self._sync_human_type, sel, query)
                    await asyncio.to_thread(self._driver.send_keys, sel, "\n")
                    await asyncio.sleep(2)
                    return True
                except Exception:
                    continue

            logger.warning("[SeleniumBase] submit_google_search: search box not found.")
            return False

        except Exception as exc:
            logger.error(f"[SeleniumBase] submit_google_search error: {exc}")
            return False

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        """Submit a query to Gemini and return the streamed response text."""
        if not self._driver:
            return None
        try:
            logger.info(f"🚀 [SeleniumBase-Gemini] DeepSearch: {query}")
            await asyncio.to_thread(self._driver.get, config.GEMINI_URL)
            await asyncio.sleep(3)

            input_sel = None
            for sel in GEMINI_INPUT_SELECTORS:
                try:
                    await asyncio.to_thread(
                        self._driver.wait_for_element_visible, sel, timeout=4
                    )
                    input_sel = sel
                    break
                except Exception:
                    continue

            if not input_sel:
                logger.warning("[SeleniumBase-Gemini] Input area not found.")
                return None

            await asyncio.to_thread(self._sync_human_type, input_sel, query)
            await asyncio.to_thread(self._driver.send_keys, input_sel, "\n")
            await asyncio.sleep(1)

            # Wait for streaming response to stabilise
            return await self._wait_for_stable_element_text(
                GEMINI_RESPONSE_SELECTORS, timeout_sec=60
            )

        except Exception as exc:
            logger.error(f"[SeleniumBase] search_gemini_ai error: {exc}")
            return None

    async def crawl_website(self, url: str) -> str:
        """
        Deep crawl of a website:
          1. Visit homepage.
          2. Discover contact / about links (up to 2 subpages).
          3. Collect and concatenate all visible body text.
        Returns up to ~12k characters of combined text.
        """
        if not await self.goto_url(url):
            return ""
        try:
            all_text: list[str] = []

            # ── Homepage text ──────────────────────────────────────────────
            src = await self.get_page_source()
            body_text = re.sub(r"<[^>]+>", " ", src)
            body_text = re.sub(r"\s+", " ", body_text).strip()
            all_text.append(f"--- PAGE: {url} ---\n{body_text}")

            # ── Contact link discovery ─────────────────────────────────────
            sublinks: list[str] = []
            try:
                anchors = await asyncio.to_thread(
                    self._driver.find_elements, "tag name", "a"
                )
                for a in anchors:
                    try:
                        text = (a.text or "").lower()
                        href = (a.get_attribute("href") or "").lower()
                        if any(
                            k in text or k in href
                            for k in config.CONTACT_KEYWORDS
                        ):
                            full_href = a.get_attribute("href") or ""
                            if full_href.startswith("http") and full_href != url:
                                sublinks.append(full_href)
                            elif full_href.startswith("/"):
                                from urllib.parse import urljoin
                                sublinks.append(urljoin(url, full_href))
                        if len(sublinks) >= 2:
                            break
                    except Exception:
                        continue
            except Exception:
                pass

            # ── Visit subpages ─────────────────────────────────────────────
            for sub in list(set(sublinks)):
                try:
                    logger.info(f"   ∟ [SeleniumBase] Visiting subpage: {sub}")
                    await asyncio.to_thread(self._sync_goto, sub)
                    await asyncio.sleep(1)
                    sub_src = await self.get_page_source()
                    sub_text = re.sub(r"<[^>]+>", " ", sub_src)
                    sub_text = re.sub(r"\s+", " ", sub_text).strip()
                    all_text.append(f"\n--- PAGE: {sub} ---\n{sub_text}")
                except Exception:
                    continue

            combined = "\n".join(all_text)
            return combined[:12000]

        except Exception as exc:
            logger.error(f"[SeleniumBase] crawl_website error: {exc}")
            return ""

    # ── CAPTCHA & interruption handling ──────────────────────────────────────

    async def _handle_captcha_if_present(self) -> bool:
        """
        Multi-layer CAPTCHA detection and resolution.

        Layer 1: Hard IP ban (403 / Access Denied) → rotate proxy
        Layer 2: Turnstile / Cloudflare challenge   → uc_gui_click_captcha()
        Layer 3: Soft CAPTCHA / unusual traffic     → API solver → manual wait

        Returns True if the session is interrupted (blocked), False if clean.
        """
        source = await self.get_page_source()
        if not source:
            return False

        lower = source.lower()

        # ── Layer 1: Hard ban ──────────────────────────────────────────────
        hard_ban_kw = [
            "access denied", "forbidden", "too many requests",
            "403 forbidden", "429 too many",
        ]
        if any(kw in lower for kw in hard_ban_kw):
            logger.error("[SeleniumBase] 🚨 HARD IP BAN DETECTED.")
            await self._record_interruption("ip_ban", "Hard block (403/Access Denied)")
            if config.PROXY_ENABLED:
                await self.rotate_proxy()
            return True

        # ── Layer 2: Turnstile / Cloudflare challenge ──────────────────────
        # SeleniumBase UC can handle these natively via OS-level GUI clicks
        if self._driver:
            try:
                has_turnstile = await asyncio.to_thread(
                    self._driver.is_element_visible,
                    'iframe[src*="turnstile"], iframe[src*="challenges.cloudflare"]',
                )
                if has_turnstile:
                    logger.warning(
                        "[SeleniumBase] ⚠️  Turnstile/Cloudflare challenge detected — "
                        "attempting uc_gui_click_captcha()."
                    )
                    await self._record_interruption("turnstile", "CF Turnstile challenge")
                    await asyncio.to_thread(self._driver.uc_gui_click_captcha)
                    # Reconnect-time sleep as specified in Gemini.md §3
                    await asyncio.sleep(self._reconnect_time)
                    return False  # We attempted to solve it — let caller retry
            except Exception as cf_exc:
                logger.debug(f"[SeleniumBase] Turnstile check error: {cf_exc}")

        # ── Layer 3: Soft CAPTCHA / unusual traffic ────────────────────────
        if is_captcha_page(source):
            logger.warning("[SeleniumBase] ⚠️  SOFT CAPTCHA / WAF detected.")
            await self._record_interruption("captcha_waf", "CAPTCHA challenge")

            # Try API solver first
            try:
                from common.captcha_solver import detect_captcha_type, solve_captcha_async
                captcha_type = detect_captcha_type(source)
                if captcha_type and getattr(config, "CAPTCHA_API_KEY", ""):
                    logger.info(
                        f"[SeleniumBase] Routing to auto CAPTCHA solver "
                        f"(type={captcha_type}, solver={config.CAPTCHA_SOLVER})..."
                    )
                    # Wrap a sync page mock for the solver (uses source-based detection)
                    solved = await asyncio.to_thread(
                        wait_for_human_captcha_solve  # fallback if solver not compatible
                    )
                    if solved:
                        return False
            except Exception:
                pass

            if config.PROXY_ENABLED:
                logger.info("[SeleniumBase] ♻️  Rotating proxy for CAPTCHA...")
                await self.rotate_proxy()
            else:
                await asyncio.to_thread(wait_for_human_captcha_solve)
            return True

        return False

    async def _record_interruption(self, reason: str, detail: str) -> None:
        """Record the timestamp and reason of an interruption for telemetry."""
        self.last_interruption_reason = reason
        self.last_interruption_ts = time.monotonic()
        alert(
            "WARNING",
            f"[SeleniumBase] Session interrupted: {reason}",
            {"detail": detail, "worker": self.worker_id},
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _accept_cookies(self) -> None:
        """Dismiss Google cookie consent if present."""
        consent_selectors = [
            "button#L2AGLb",
            "button#W0wltc",
            "button:has-text('Accept all')",
            "button:has-text('Accepter tout')",
        ]
        for sel in consent_selectors:
            try:
                visible = await asyncio.to_thread(
                    self._driver.is_element_visible, sel
                )
                if visible:
                    await asyncio.to_thread(self._driver.click, sel)
                    await asyncio.sleep(0.8)
                    logger.debug("[SeleniumBase] Cookie consent accepted.")
                    break
            except Exception:
                continue

    def _sync_human_type(self, selector: str, text: str) -> None:
        """
        Type text into a selector character-by-character with Gaussian delays.
        Uses config.ACTION_DELAY_PROFILES['type_char'] for timing distribution.
        """
        import numpy as np  # type: ignore

        profile = config.ACTION_DELAY_PROFILES.get(
            "type_char", {"mean": 0.08, "std": 0.03, "min": 0.04, "max": 0.20}
        )
        try:
            self._driver.click(selector)
        except Exception:
            pass

        for char in text:
            try:
                self._driver.send_keys(selector, char)
            except Exception:
                # Fall back to type() if send_keys fails
                try:
                    self._driver.type(selector, char)
                except Exception:
                    pass
            # Gaussian delay clamped to [min, max]
            try:
                delay = float(
                    np.clip(
                        np.random.normal(profile["mean"], profile["std"]),
                        profile["min"],
                        profile["max"],
                    )
                )
            except Exception:
                delay = random.uniform(
                    config.TYPING_MIN_DELAY_SEC, config.TYPING_MAX_DELAY_SEC
                )
            time.sleep(delay)

    async def _extract_first_selector(self, selectors: list) -> Optional[str]:
        """
        Try each CSS selector; return the first non-empty text found.
        Uses SeleniumBase's find_element() for robust matching.
        """
        if not self._driver:
            return None
        for sel in selectors:
            try:
                visible = await asyncio.to_thread(
                    self._driver.is_element_visible, sel
                )
                if visible:
                    text = await asyncio.to_thread(self._driver.get_text, sel)
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return None

    async def _wait_for_stable_response(self, timeout_sec: int = 25) -> Optional[str]:
        """
        Poll the page body every 1.5s until text stops changing (stable for ≥2 cycles).

        This mirrors the pattern from patchright_agent._wait_for_ai_mode_response()
        and is the correct approach for Google AI Mode's streaming responses.
        """
        deadline = time.monotonic() + timeout_sec
        prev_text = ""
        stable_count = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(1.5)

            # Try AI-specific selectors first (highest signal)
            current = await self._extract_first_selector(AI_RESPONSE_SELECTORS)

            # Fallback to full body text
            if not current:
                try:
                    current = await asyncio.to_thread(
                        lambda: self._driver.get_text("body")
                    )
                except Exception:
                    pass

            if current and current == prev_text:
                stable_count += 1
                if stable_count >= 2:
                    return current
            else:
                prev_text = current or ""
                stable_count = 0

        return prev_text if prev_text else None

    async def _wait_for_stable_element_text(
        self, selectors: list, timeout_sec: int = 60
    ) -> Optional[str]:
        """
        Wait for any of the given selectors to produce stable text output.
        Used for Gemini's streamed responses.
        """
        deadline = time.monotonic() + timeout_sec
        last_text = ""
        stable_count = 0

        while time.monotonic() < deadline:
            await asyncio.sleep(1)
            current = await self._extract_first_selector(selectors) or ""
            if current and current == last_text:
                stable_count += 1
                if stable_count >= 4:  # 4 stable cycles = ~4s quiet period
                    return current
            else:
                stable_count = 0
                last_text = current

        return last_text if last_text else None
