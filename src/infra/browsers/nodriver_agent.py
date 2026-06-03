"""
browser/nodriver_agent.py - Tier 5: CDP Direct Control

Fixes applied:
1. no_sandbox / sandbox=False for Docker root user (os.getuid() == 0)
2. Correct nd.start() API: `browser_args` kwarg (was `args`), no `proxy` kwarg
3. Proxy injected as CLI arg: --proxy-server=<proxy>
4. Removed Playwright API leakage: no `contexts` / `launch_context` on Browser
   → Navigation: `await browser.get(url)` → Tab
   → Initial page:  `browser.main_tab`
5. Fixed page content API: `Tab.get_content()` (was `Tab.content()`)
6. `search_google_ai_mode` signature aligned with BaseBrowserAgent (**kwargs)
7. Removed unused variable `uc_js` and unused import `core.config`
"""

from __future__ import annotations

import asyncio
import os
from typing import Any

from agents.base_agent import BaseBrowserAgent
from core.logger import alert, get_logger

logger = get_logger(__name__)


class NodriverAgent(BaseBrowserAgent):
    """
    Tier 5 scraper using nodriver (undetected Chrome via CDP — no WebDriver).
    Direct CDP control for maximum stealth on hard WAFs.

    Key differences from Playwright-based agents:
    - No browser contexts: Browser exposes tabs directly.
    - Navigation:  `page = await browser.get(url)` returns a Tab.
    - Content:     `await tab.get_content()` (not `.content()`).
    - Proxy:       passed as Chrome CLI arg `--proxy-server=`, not a kwarg.
    """

    def __init__(self, worker_id: int = 0) -> None:
        super().__init__(worker_id)
        self._browser = None
        self._page = None  # nodriver Tab (no separate context layer)
        self.current_proxy: str | None = None
        self._lock = asyncio.Lock()
        self._last_content: str = ""

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> bool:
        """Start nodriver browser with no_sandbox fix for Docker."""
        async with self._lock:
            return await self._start_internal()

    async def _start_internal(self) -> bool:
        """Internal launch — must be called with self._lock held."""
        try:
            import nodriver as nd

            logger.info("[Nodriver] Starting browser...")

            # sandbox=False is required when running as root (Docker)
            running_as_root = os.getuid() == 0
            browser_args: list[str] = []
            if running_as_root:
                browser_args += ["--no-sandbox", "--disable-setuid-sandbox"]

            # Proxy injected as Chrome CLI argument (nodriver does NOT accept proxy kwarg)
            if self.current_proxy:
                browser_args.append(f"--proxy-server={self.current_proxy}")

            self._browser = await nd.start(
                headless=True,
                browser_args=browser_args,
                sandbox=False,  # force False for reliability in containerised environments
                user_data_dir=None,
            )

            # Guard against nd.start() returning None silently (CDP connection failure)
            if self._browser is None:
                logger.error("[Nodriver] Failed to start: nd.start() returned None (CDP connection failed)")
                self._browser = None
                self._page = None
                return False

            self._page = self._browser.main_tab

            alert("INFO", "Nodriver session started", {"proxy": self.current_proxy or "direct"})
            logger.info("[Nodriver] Ready.")
            return True

        except Exception as e:
            logger.error(f"[Nodriver] Failed to start: {e}")
            self._browser = None
            self._page = None
            return False

    async def close(self) -> None:
        async with self._lock:
            if self._browser:
                try:
                    await self._browser.stop()
                except Exception:
                    pass
                finally:
                    self._browser = None
                    self._page = None
            logger.info("[Nodriver] Closed.")

    async def is_alive(self) -> bool:
        async with self._lock:
            return self._browser is not None

    # ── Navigation ─────────────────────────────────────────────────────────

    async def goto_url(self, url: str) -> bool:
        """Navigate to URL.

        FIX: nodriver navigation is `browser.get(url)` → returns a Tab.
             This is NOT `context.new_page()` (Playwright API).
        """
        async with self._lock:
            try:
                if not self._browser:
                    if not await self._start_internal():
                        return False

                # FIX 4 (continued): Browser.get(url) is the correct navigation API
                assert self._browser is not None
                self._page = await self._browser.get(url)
                await asyncio.sleep(2)  # Let page stabilize
                return True

            except Exception as e:
                logger.error(f"[Nodriver] goto_url error: {e}")
                return False

    # ── Content extraction ─────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Get current page HTML.

        FIX 5: nodriver Tab exposes `get_content()`, NOT `content()`.
        """
        async with self._lock:
            try:
                if self._page:
                    content = await self._page.get_content()
                    self._last_content = content
                    return content
                return ""
            except Exception as e:
                logger.error(f"[Nodriver] get_page_source error: {e}")
                return ""

    async def scrape(self, url: str) -> str | None:
        """Scrape URL and return page HTML."""
        if await self.goto_url(url):
            return await self.get_page_source()
        return None

    # ── Search / AI-mode methods ───────────────────────────────────────────

    async def submit_google_search(self, query: str) -> bool:
        """Submit a Google search via URL navigation."""
        try:
            return await self.goto_url(f"https://www.google.com/search?q={query}")
        except Exception as e:
            logger.error(f"[Nodriver] submit_google_search error: {e}")
            return False

    async def extract_universal_data(self, use_browser: bool = False) -> dict:  # type: ignore[override]
        """Extract structured data from current page (stub — extend as needed)."""
        return {}

    async def search_google_ai_mode(
        self,
        prompt: str,
        ai_mode_url: str | None = None,
        row: Any | None = None,
        **kwargs: Any,
    ) -> str | None:
        """Fetch AI Mode URL content via nodriver.

        FIX 6: signature now includes **kwargs to match BaseBrowserAgent contract.
        Extra named params (ai_mode_url, row) are forwarded by the HybridEngine
        via **kwargs — keeping both specific names AND open extensibility.
        """
        if not ai_mode_url:
            return None
        return await self.scrape(ai_mode_url)

    # ── WAF detection ──────────────────────────────────────────────────────

