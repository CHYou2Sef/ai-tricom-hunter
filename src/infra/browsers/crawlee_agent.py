"""
 ╔══════════════════════════════════════════════════════════════════════════╗
 ║  infra/browsers/crawlee_agent.py                                          ║
 ║                                                                          ║
 ║  TIER 8 — Crawlee (Adaptive / Playwright Crawler)                        ║
 ║                                                                          ║
 ║  Role: Industrial-grade crawling and extraction using the Crawlee        ║
 ║  framework. Handles dynamic content and complex navigation.             ║
 ╚══════════════════════════════════════════════════════════════════════════╝
 """
from __future__ import annotations
import asyncio
from typing import Optional, Any
from crawlee.crawlers import PlaywrightCrawler, PlaywrightCrawlingContext

from agents.base_agent import BaseBrowserAgent
from core.logger import get_logger
 
logger = get_logger(__name__)
 
class CrawleeAgent(BaseBrowserAgent):
    """
    Agent using the Crawlee framework for robust, scalable scraping.
    Uses PlaywrightCrawler internally for full JS rendering support.
    """
    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._last_html: str = ""
        self._crawler: Optional[PlaywrightCrawler] = None
        self._lock = asyncio.Lock()

    async def start(self) -> None:
        """Initialize the Crawlee crawler."""
        async with self._lock:
            if self._crawler:
                return
             
            logger.info(f"[Crawlee] 🚀 Initializing PlaywrightCrawler (worker={self.worker_id})...")
            self._crawler = PlaywrightCrawler(
                max_requests_per_crawl=1,
                request_handler=self._handle_request,
                headless=True,
                browser_type='chromium',
            )

    async def is_alive(self) -> bool:
        """Check if the agent is ready to crawl."""
        return self._crawler is not None

    async def _handle_request(self, context: PlaywrightCrawlingContext) -> None:
        """
        Request handler for Crawlee.
        Captures the page source for our agent.
        """
        try:
            url = context.request.url
            logger.debug(f"[Crawlee] Processing: {url}")
            self._last_html = await context.page.content()
        except Exception as e:
            logger.error(f"[Crawlee] Error in request handler: {e}")
            self._last_html = ""

    async def close(self) -> None:
        """Teardown Crawlee resources."""
        async with self._lock:
            self._crawler = None
            logger.info("[Crawlee] Agent closed.")

    async def get_page_source(self) -> str:
        """Return the HTML captured during the last crawl."""
        return self._last_html

    async def goto_url(self, url: str) -> bool:
        """Navigate to a URL using Crawlee's crawler logic."""
        # Ensure started first
        if not self._crawler:
            await self.start()
            
        async with self._lock:
            if not self._crawler:
                logger.error("[Crawlee] Crawler not initialized.")
                return False
                
            logger.info(f"[Crawlee] Navigating to: {url}")
            self._last_html = ""
                
            try:
                await self._crawler.run([url])
                return bool(self._last_html)
            except Exception as e:
                logger.error(f"[Crawlee] Error navigating to {url}: {e}")
                return False

    async def crawl_website(self, url: str) -> str:
        """Leverage Crawlee for a single-page 'crawl'."""
        if await self.goto_url(url):
            return self._last_html
        return ""

    # ── Stub methods for BaseBrowserAgent contract ─────────────────────────
    
    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None) -> Optional[str]:
        """
        Implémentation de la recherche pour Crawlee (Tier 8).
        Extrait les termes de recherche et lance un mini-crawl sur Google Search.
        """
        import re
        from common.search_engine import generate_google_ai_url

        if ai_mode_url:
            logger.info(f"[Crawlee] Navigating direct AI Mode URL: {ai_mode_url}")
            if await self.goto_url(ai_mode_url):
                return self._last_html
            return None

        search_query = prompt
        if len(prompt) > 200 or "###" in prompt:
            name_match = re.search(r"NAME:\s*(.*)", prompt)
            addr_match = re.search(r"ADDRESS:\s*(.*)", prompt)
            if name_match:
                search_query = name_match.group(1).strip()
                if addr_match:
                    search_query += f" {addr_match.group(1).strip()}"
            else:
                search_query = prompt[:150]

        url = generate_google_ai_url(search_query)
        logger.info(f"[Crawlee] 🔍 Recherche Google pour: {search_query}")
        
        if await self.goto_url(url):
            return self._last_html
        return None

    async def search_google_ai(self, query: str, ai_mode_url: Optional[str] = None) -> Optional[str]:
        return await self.search_google_ai_mode(query, ai_mode_url=ai_mode_url)

    async def search_google_ai_interactive(self, prompt: str, row: Optional[Any] = None) -> Optional[str]:
        return await self.search_google_ai_mode(prompt)

    async def submit_google_search(self, query: str) -> bool:
        return False

    async def rotate_proxy(self) -> None:
        pass