"""
browser/nodriver_agent.py - Tier 5: CDP Direct Control (Fixed)

Fixes applied:
1. no_sandbox=True for Docker root user
2. Robust browser launch with error handling
"""

from __future__ import annotations
import asyncio
import os
from typing import Optional, Any

from core import config
from core.logger import get_logger, alert

logger = get_logger(__name__)

from agents.base_agent import BaseBrowserAgent


class NodriverAgent(BaseBrowserAgent):
    """
    Tier 5 scraper using nodriver (undetected-playwright without WebDriver).
    Direct CDP control for maximum stealth on hard WAFs.
    FIXED: no_sandbox for Docker root user.
    """

    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._browser = None
        self._context = None
        self._page = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        self._last_content: str = ""

    async def start(self) -> bool:
        """Start nodriver browser with no_sandbox fix for Docker."""
        async with self._lock:
            return await self._start_internal()

    async def _start_internal(self) -> bool:
        try:
            import nodriver as nd
            
            logger.info("[Nodriver] Starting browser...")
            
            # CRITICAL FIX: no_sandbox for Docker root user
            browser_args = []
            if os.getuid() == 0:
                browser_args = ["--no-sandbox", "--disable-setuid-sandbox"]
            
            # Build proxy extension if needed
            uc_js = ""  # placeholder
            
            self._browser = await nd.start(
                headless=True,
                args=browser_args,
                proxy=self.current_proxy,
                user_data_dir=None,
            )
            
            self._context = await self._browser.contexts()[0] if self._browser.contexts() else await self._browser.launch_context()
            
            alert("INFO", "Nodriver session started", {"proxy": self.current_proxy or "direct"})
            logger.info("[Nodriver] Ready.")
            return True
            
        except Exception as e:
            logger.error(f"[Nodriver] Failed to start: {e}")
            self._browser = None
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
                    self._context = None
                    self._page = None
            logger.info("[Nodriver] Closed.")

    async def is_alive(self) -> bool:
        async with self._lock:
            return self._browser is not None

    async def goto_url(self, url: str) -> bool:
        """Navigate to URL."""
        async with self._lock:
            try:
                if not self._browser:
                    if not await self._start_internal():
                        return False
                
                if not self._context:
                    self._context = await self._browser.launch_context()
                
                self._page = await self._context.new_page()
                await self._page.goto(url, timeout=self.get_adaptive_timeout_ms(30000))
                await asyncio.sleep(2)  # Let page stabilize
                return True
                
            except Exception as e:
                logger.error(f"[Nodriver] goto_url error: {e}")
                return False

    async def get_page_source(self) -> str:
        """Get current page HTML."""
        async with self._lock:
            try:
                if self._page:
                    content = await self._page.content()
                    self._last_content = content
                    return content
                return ""
            except Exception as e:
                logger.error(f"[Nodriver] get_page_source error: {e}")
                return ""

    async def scrape(self, url: str) -> Optional[str]:
        """Scrape URL and return content."""
        if await self.goto_url(url):
            return await self.get_page_source()
        return None

    # ── SEARCH METHODS ──

    async def submit_google_search(self, query: str) -> bool:
        """Submit Google search via nodriver."""
        try:
            return await self.goto_url(f"https://www.google.com/search?q={query}")
        except Exception as e:
            logger.error(f"[Nodriver] submit_google_search error: {e}")
            return False

    async def extract_universal_data(self, use_browser: bool = False) -> dict:
        """Extract structured data from current page."""
        return {}  # Simplified - extend as needed

    async def search_google_ai_mode(
        self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None
    ) -> Optional[str]:
        """Fetch AI Mode URL content."""
        if not ai_mode_url:
            return None
        return await self.scrape(ai_mode_url)

    def is_block_response(self, content: str) -> bool:
        """Detect blocking/WAF."""
        if not content:
            return True
        block_patterns = [
            "access denied", "blocked", "forbidden", "captcha",
            "rate limit", "too many requests", "403 forbidden"
        ]
        lower = content.lower()
        return sum(1 for p in block_patterns if p in lower) >= 3
