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
 
import asyncio
from typing import Optional
from crawlee.playwright_crawler import PlaywrightCrawler, PlaywrightCrawlingContext

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
 
    async def start(self) -> None:
        """
         Initialize the Crawlee crawler.
         """
        if self._crawler:
            return
         
        logger.info(f"[Crawlee] 🚀 Initializing PlaywrightCrawler (worker={self.worker_id})...")
        # We define the crawler but don't 'run' it yet. 
        # Crawlee is designed for batch runs, but we can use it for single pages
        # by running it on a list of 1 URL.
        self._crawler = PlaywrightCrawler(
            max_requests_per_crawl=1,
            request_handler=self._handle_request,
            headless=True,
            browser_type='chromium',
        )
 
    async def _handle_request(self, context: PlaywrightCrawlingContext) -> None:
        """
        Request handler for Crawlee.
        Captures the page source for our agent.
        """
        url = context.request.url
        logger.debug(f"[Crawlee] Processing: {url}")
        self._last_html = await context.page.content()
        
        # We could also use Crawlee's built-in dataset storage if needed:
        # await context.push_data({'url': url, 'html_len': len(self._last_html)})

    async def close(self) -> None:
        """Teardown Crawlee resources."""
        # Note: Crawlee handles its own lifecycle during .run(), 
        # but we keep this for interface compatibility.
        self._crawler = None
        logger.info("[Crawlee] Agent closed.")

    async def get_page_source(self) -> str:
        """Return the HTML captured during the last crawl."""
        return self._last_html

    async def goto_url(self, url: str) -> bool:
        """
        Navigate to a URL using Crawlee's crawler logic.
        """
        if not self._crawler:
            await self.start()
            
        logger.info(f"[Crawlee] Navigating to: {url}")
        self._last_html = ""
            
        try:
            # Running on a single URL
            await self._crawler.run([url])
            return bool(self._last_html)
        except Exception as e:
            logger.error(f"[Crawlee] Error navigating to {url}: {e}")
            return False

    async def crawl_website(self, url: str) -> str:
        """
        Leverage Crawlee for a single-page 'crawl'.
        """
        if await self.goto_url(url):
            return self._last_html
        return ""

    # ── Stub methods for BaseBrowserAgent contract ─────────────────────────
    
    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """Crawlee is best for direct scraping, not search engine interaction."""
        return None 

    async def submit_google_search(self, query: str) -> bool:
        return False

    async def rotate_proxy(self) -> None:
        # Crawlee has built-in proxy support we could configure in __init__
        pass

    async def search_google_ai(self, query: str) -> Optional[str]:
        return None