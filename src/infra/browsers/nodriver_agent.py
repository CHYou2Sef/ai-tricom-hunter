"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/nodriver_agent.py                                               ║
║                                                                          ║
║  TASK 1 from GEMINI.md — Tier 2: Stealth CDP Agent                      ║
║                                                                          ║
║  Uses Nodriver (UC-Mode) which launches Chrome via CDP only —            ║
║  NO WebDriver flag, NO automation-controlled banner.                     ║
║  Passes bot.sannysoft.com with zero red flags.                           ║
║                                                                          ║
║  Features:                                                               ║
║    ✓ Zero WebDriver fingerprint (CDP-only launch)                        ║
║    ✓ Full fingerprint bundle injection at session start                  ║
║    ✓ Per-action delay matrix (action_delay_async)                        ║
║    ✓ Stale connection detection + exponential backoff reconnect          ║
║    ✓ Integrated CAPTCHA detection → solver pipeline                      ║
║    ✓ Proxy support per browser context                                   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import os
import asyncio
import re
from typing import Optional, List, Dict, Any

from core import config
from agents.base_agent import BaseBrowserAgent
from common.anti_bot import (
    get_fingerprint_bundle,
    build_cdp_injection_script,
    action_delay_async,
    is_captcha_page,
)
from core.logger import get_logger, alert, stale_connection_alert
from common.captcha_solver import detect_captcha_type, solve_captcha_async

logger = get_logger(__name__)


class NodriverAgent(BaseBrowserAgent):
    """
    Tier 2 stealth browser agent built on Nodriver (UC-Mode / CDP-only).

    This agent is routed to by the HybridEngine when the target URL
    matches config.HYBRID_TIER2_DOMAINS (Cloudflare-protected sites).
    """

    def __init__(self, worker_id: int = 0, proxy: Optional[str] = None):
        super().__init__(worker_id)
        self._browser = None
        self._page = None
        self.current_proxy = proxy
        self._reconnect_count: int = 0
        self._lock = asyncio.Lock()
        self._bundle = None

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Launch Nodriver browser with CDP-only mode."""
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        """Internal lock-free start. Assumes lock is held."""
        if self._browser:
            return
            
        try:
            import nodriver as nd  # type: ignore
        except ImportError:
            raise RuntimeError("nodriver is not installed. Run 'pip install nodriver'")

        self._bundle = get_fingerprint_bundle()
        vp = self._bundle["viewport"]
        logger.info(f"[Nodriver] 🚀 Starting stealth browser ({vp['width']}×{vp['height']})")

        # ── Chrome CLI Flags ──────────────────────────────────────────────────
        # These flags are critical for stability in containerized environments.
        browser_args = [
            f"--window-size={vp['width']},{vp['height']}",
            "--no-first-run",
            "--no-default-browser-check",
            "--disable-infobars",
            "--disable-notifications",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--remote-debugging-port=0", # Auto-assign
        ]

        # 🛡️ SANDBOX FIX: If running as root (UID 0), Chrome MUST have these flags
        # or it will immediately crash with a 'failed to set sandbox' error.
        if os.getuid() == 0:
            logger.warning("[Nodriver] Running as ROOT. Applying --no-sandbox flags.")
            if "--no-sandbox" not in browser_args:
                browser_args.append("--no-sandbox")
            if "--disable-setuid-sandbox" not in browser_args:
                browser_args.append("--disable-setuid-sandbox")

        if self.current_proxy:
            if "@" in self.current_proxy:
                from common.anti_bot import create_proxy_auth_extension
                ext_path = create_proxy_auth_extension(self.current_proxy, self.worker_id)
                if ext_path:
                    logger.info(f"[Nodriver] 🔑 Using AUTH proxy extension")
                    browser_args.append(f"--load-extension={ext_path}")
                else:
                    browser_args.append(f"--proxy-server={self.current_proxy}")
            else:
                browser_args.append(f"--proxy-server={self.current_proxy}")

        profile_path = config.get_worker_profile_path(self.worker_id, "nodriver")
        nd_path = config.CHROMIUM_BINARY_PATH if config.CHROMIUM_BINARY_PATH else None

        try:
            # 🚀 Launch browser via CDP
            self._browser = await nd.start(
                browser_executable_path=nd_path,
                browser_args=browser_args,
                user_data_dir=profile_path,
                headless=getattr(config, "HEADLESS", False)
            )

            await asyncio.sleep(2)
            if not self._browser:
                raise RuntimeError("[Nodriver] Browser object is None after start.")
                
            self._page = self._browser.main_tab
            await self._inject_fingerprint_locked(self._page)
            logger.info("[Nodriver] ✅ Ready.")
        except Exception as e:
            logger.error(f"[Nodriver] Failed to start: {e}")
            self._browser = self._page = None
            raise

    async def close(self) -> None:
        """Stop the browser and release all resources."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
        try:
            if self._browser:
                self._browser.stop()
        except Exception:
            pass
        finally:
            self._browser = self._page = None
            self._reconnect_count = 0
            logger.info("[Nodriver] Browser closed.")

    async def rotate_proxy(self) -> None:
        """Standardized rotation: drop current browser, get new proxy, restart."""
        async with self._lock:
            await self._rotate_proxy_locked()

    async def _rotate_proxy_locked(self) -> None:
        """Internal lock-free rotation."""
        from common.proxy_manager import get_next_proxy
        new_proxy = await get_next_proxy()
        if new_proxy:
            logger.info(f"[Nodriver] ♻️  Rotating proxy to: {new_proxy}")
            self.current_proxy = new_proxy
            await self._close_locked()
            await self._start_locked()
        else:
            logger.warning("[Nodriver] No fresh proxy available for rotation.")

    async def is_alive(self) -> bool:
        """Public health check with lock protection. Passive."""
        async with self._lock:
            if not self._page or not self._browser:
                return False
            try:
                # Use a shorter timeout for the public health check
                await asyncio.wait_for(self._page.evaluate("1+1"), timeout=2.0)
                return True
            except Exception:
                return False

    # ─────────────────────────────────────────────────────────────────
    # STALE CONNECTION RECOVERY
    # ─────────────────────────────────────────────────────────────────

    async def _ensure_page_locked(self) -> bool:
        """
        Check if the page is responsive. Internal locked version.
        Includes a 5s health-check cache to prevent redundant evaluation.
        Attempts recovery if dead.
        """
        import time
        now = time.time()
        
        # 1. Immediate NoneType check
        if not self._page or not self._browser:
            logger.info("[Nodriver] 🔄 Session missing, starting new one...")
            await self._start_locked()
            return self._page is not None

        # 2. 5s health-check cache to avoid spamming 1+1
        if getattr(self, "_last_health_check", 0) > (now - 5):
            return True

        try:
            # Heartbeat check via simple JS evaluation
            await asyncio.wait_for(
                self._page.evaluate("1+1"),
                timeout=config.BROWSER_STALE_TIMEOUT_SEC,
            )
            self._reconnect_count = 0  # Reset on success
            self._last_health_check = now
            return True

        except (asyncio.TimeoutError, Exception) as exc:
            logger.warning(f"[Nodriver] 💔 Page unresponsive (heartbeat failed): {exc}. Resurrecting...")
            self._reconnect_count += 1
            stale_connection_alert(
                attempt=self._reconnect_count,
                max_attempts=config.BROWSER_MAX_RECONNECT_ATTEMPTS,
                detail=str(exc),
            )

            if self._reconnect_count >= config.BROWSER_MAX_RECONNECT_ATTEMPTS:
                logger.error("[Nodriver] 💀 All reconnect attempts exhausted.")
                await self._close_locked()
                return False

            # Exponential backoff before restart
            backoff = config.PROXY_BACKOFF_DELAYS[
                min(self._reconnect_count - 1, len(config.PROXY_BACKOFF_DELAYS) - 1)
            ]
            logger.info(f"[Nodriver] ♻️ Reconnecting in {backoff}s...")
            await asyncio.sleep(backoff)

            await self._close_locked()
            await self._start_locked()
            if self._page:
                self._last_health_check = time.time()
                return True
            return False

    # ─────────────────────────────────────────────────────────────────
    # FINGERPRINT INJECTION
    # ─────────────────────────────────────────────────────────────────

    async def _inject_fingerprint_locked(self, page) -> None:
        """Inject fingerprint into the given page instance."""
        if not self._bundle or not page: return
        script = build_cdp_injection_script(self._bundle)
        try:
            await page.evaluate(script)
        except Exception as exc:
            logger.warning(f"[Nodriver] Fingerprint error: {exc}")

    # ─────────────────────────────────────────────────────────────────
    # NAVIGATION
    # ─────────────────────────────────────────────────────────────────

    async def goto_url(self, url: str) -> bool:
        """Navigate to a URL and wait for page load."""
        async with self._lock:
            return await self._goto_url_locked(url)

    async def _goto_url_locked(self, url: str) -> bool:
        if not await self._ensure_page_locked():
            return False
            
        try:
            logger.info(f"[Nodriver] → {url}")
            if not self._page: return False
            await self._page.get(url)
            await action_delay_async("navigate")
            await self._handle_captcha_if_present_locked(self._page)
            
            # Post-navigation health check (detect immediate blocks)
            content = await self._page.get_content()
            if self.is_block_response(content):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return False
                
            return True
        except Exception as exc:
            if self.is_block_response(exc):
                await self.report_proxy_error(self.current_proxy, 403)
            
            logger.error(f"[Nodriver] Navigation error: {exc}")
            return False

    async def get_page_source(self) -> str:
        """Return the raw HTML of the current page."""
        async with self._lock:
            return await self._get_page_source_locked()

    async def _get_page_source_locked(self) -> str:
        if not self._page:
            return self._last_content
        try:
            content = await self._page.get_content()
            self._last_content = content or ""
            return self._last_content
        except Exception:
            return self._last_content

    # ─────────────────────────────────────────────────────────────────
    # SEARCH METHODS
    # ─────────────────────────────────────────────────────────────────

    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Submit a query to Google via AI Mode URL."""
        async with self._lock:
            return await self._search_google_ai_locked(prompt, ai_mode_url, row=row)

    async def _search_google_ai_locked(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Internal lock-free search."""
        if not await self._ensure_page_locked():
            return None
        
        if not self._page: return None

        try:
            from common.search_engine import generate_google_ai_url
            url = ai_mode_url or generate_google_ai_url(prompt)

            logger.info(f"[Nodriver] 🔍 Google AI Mode: {prompt}")
            await self._page.get(url)
            await action_delay_async("read_wait")

            if not self._page: return None
            interrupted = await self._handle_captcha_if_present_locked(self._page)
            if interrupted:
                if not await self._ensure_page_locked():
                    return None
                await self._page.get(url)
                await action_delay_async("read_wait")

            if not self._page: return None
            content = await self._page.get_content()
            
            # Post-navigation health check (detect immediate blocks)
            if self.is_block_response(content):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return None

            logger.info(f"[Nodriver] ✅ Got {len(content)} chars.")
            return content
        except Exception as exc:
            logger.error(f"[Nodriver] search_google_ai error: {exc}")
            if self.is_block_response(exc):
                await self.report_proxy_error(self.current_proxy, 403)
            return None

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Alias for search_google_ai to maintain HybridEngine compatibility."""
        return await self.search_google_ai(prompt, ai_mode_url=ai_mode_url, row=row)


    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Interactive search fallback for Nodriver."""
        return await self.search_google_ai(prompt, ai_mode_url=ai_mode_url, row=row)

    async def submit_google_search(self, prompt: str) -> bool:
        """Navigate to Google and submit a search query."""
        async with self._lock:
            return await self._submit_google_search_locked(prompt)

    async def _submit_google_search_locked(self, prompt: str) -> bool:
        """Internal lock-free submit."""
        if not await self._ensure_page_locked():
            return False
        
        if not self._page: return False
        
        try:
            import urllib.parse
            encoded = urllib.parse.quote_plus(prompt)
            url = f"https://www.google.com/search?q={encoded}"
            logger.info(f"[Nodriver] 🔍 Google Search: {prompt}")
            await self._page.get(url)
            await action_delay_async("navigate")
            
            if not self._page: return False
            await self._handle_captcha_if_present_locked(self._page)
            
            if not self._page: return False
            content = await self._page.get_content()

            # Detect immediate block
            if self.is_block_response(content):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return False

            return bool(content and len(content) > 500)
        except Exception as exc:
            logger.error(f"[Nodriver] submit_google_search error: {exc}")
            if self.is_block_response(exc):
                await self.report_proxy_error(self.current_proxy, 403)
            return False

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
        """Submit a query to Gemini via direct interaction."""
        async with self._lock:
            return await self._search_gemini_ai_locked(prompt)

    async def _search_gemini_ai_locked(self, prompt: str) -> Optional[str]:
        if not await self._ensure_page_locked():
            return None
        try:
            logger.info(f"[Nodriver] 🤖 Gemini: {prompt}")
            if not self._page: return None
            await self._page.get(config.GEMINI_URL)
            await action_delay_async("navigate")
            
            if not self._page: return None
            await self._type_text_locked(self._page, prompt)
            await action_delay_async("submit")
            await action_delay_async("read_wait")
            
            if not self._page: return None
            content = await self._page.get_content()
            
            if self.is_block_response(content):
                await self.report_proxy_error(self.current_proxy)
                return None
                
            return content
        except Exception as exc:
            logger.error(f"[Nodriver] search_gemini_ai error: {exc}")
            if self.is_block_response(exc):
                await self.report_proxy_error(self.current_proxy)
            return None

    async def _type_text_locked(self, page, text: str) -> None:
        """Type text character-by-character into the focused element."""
        if not page: return
        for char in text:
            try:
                # Defensive check inside loop
                if not self._page: break
                await page.keyboard.send(char)
                await action_delay_async("type_char")
            except Exception:
                break

    async def crawl_website(self, url: str) -> str:
        """Alias for crawl_url to maintain HybridEngine contract."""
        return await self.crawl_url(url)

    async def crawl_url(self, url: str) -> str:
        """Visit a URL and return all visible text from the body."""
        async with self._lock:
            return await self._crawl_url_locked(url)

    async def _crawl_url_locked(self, url: str) -> str:
        """Internal lock-free crawl."""
        if not await self._goto_url_locked(url):
            return ""
        try:
            html = await self._get_page_source_locked()
            
            if self.is_block_response(html):
                await self.report_proxy_error(self.current_proxy)
                return ""
                
            # Strip tags for clean text extraction
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:8000]
        except Exception as exc:
            logger.error(f"[Nodriver] crawl_url error: {exc}")
            return ""

    # ─────────────────────────────────────────────────────────────────
    # CAPTCHA INTEGRATION
    # ─────────────────────────────────────────────────────────────────

    async def _handle_captcha_if_present_locked(self, page) -> bool:
        """Detect and solve CAPTCHA. Returns True if rotation triggered."""
        if not page: return False
        try:
            html = await page.get_content()
            captcha_type = detect_captcha_type(html)
            if captcha_type:
                solved = await solve_captcha_async(page, captcha_type)
                if not solved:
                    logger.warning("[Nodriver] CAPTCHA failed. Rotating...")
                    await self.report_proxy_error(self.current_proxy, 403)
                    await self._rotate_proxy_locked()
                    return True
            return False
        except Exception as e:
            logger.debug(f"[Nodriver] Captcha check error: {e}")
            return False

    # ─────────────────────────────────────────────────────────────────
    # PRIVATE HELPERS
    # ─────────────────────────────────────────────────────────────────

    async def generate_human_noise(self) -> None:
        """Simulate human browsing in Nodriver (CDP-only)."""
        async with self._lock:
            await self._generate_human_noise_locked()

    async def _generate_human_noise_locked(self) -> None:
        """Internal lock-free noise simulation."""
        import random
        if not self._browser:
            return
            
        site = random.choice(config.HUMAN_NOISE_SITES)
        logger.info(f"🎭 [Human Noise] Simulating activity on: {site}")
        
        try:
            if not self._browser: return
            noise_tab = await self._browser.get(site, new_tab=True)
            if not noise_tab: return
            
            await asyncio.sleep(random.uniform(5, 12))
            for _ in range(random.randint(2, 5)):
                if not self._browser or not noise_tab: break
                await noise_tab.scroll_down(random.randint(300, 800))
                await asyncio.sleep(random.uniform(1, 3))
            
            if noise_tab:
                await noise_tab.close()
            logger.info("🎭 [Human Noise] Simulation complete.")
        except Exception as exc:
            logger.debug(f"[Human Noise] Simulation error: {exc}")

