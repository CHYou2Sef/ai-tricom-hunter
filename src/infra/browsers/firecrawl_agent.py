"""
╔══════════════════════════════════════════════════════════════════════════╗
║  infra/browsers/firecrawl_agent.py                                        ║
║                                                                          ║
║  Role: Premium Managed Scraper (Firecrawl SDK).                          ║
║  Used for hard-to-scrape sites, structured extraction, and mass crawls.  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
from typing import Optional, Dict, Any, List
from firecrawl import FirecrawlApp
from core import config
from core.logger import get_logger

logger = get_logger(__name__)

class FirecrawlAgent:
    """
    Wrapper for the Firecrawl SDK.
    Provides high-level methods for scraping, crawling, and AI-powered extraction.
    """
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or config.FIRECRAWL_API_KEY
        self.enabled = config.FIRECRAWL_ENABLED and bool(self.api_key)
        self._app = None
        
        if self.enabled:
            try:
                self._app = FirecrawlApp(api_key=self.api_key)
                logger.info("[Firecrawl] SDK initialized.")
            except Exception as e:
                logger.error(f"[Firecrawl] Failed to initialize: {e}")
                self.enabled = False

    async def scrape(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Scrape a single URL to Markdown/HTML."""
        if not self.enabled:
            return None
            
        logger.info(f"[Firecrawl] Scraping: {url}")
        try:
            # SDK is synchronous, but we can run in thread if needed. 
            # For now, simple direct call as this is typically called in async worker.
            result = self._app.scrape_url(url, params=params)
            return result
        except Exception as e:
            logger.error(f"[Firecrawl] Scrape failed for {url}: {e}")
            return None

    async def extract(self, urls: List[str], prompt: str, schema: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        AI-powered structured extraction from one or more URLs.
        """
        if not self.enabled:
            return None
            
        logger.info(f"[Firecrawl] Extracting from {len(urls)} URLs...")
        try:
            result = self._app.extract(urls, {
                "prompt": prompt,
                "schema": schema
            } if schema else {"prompt": prompt})
            return result
        except Exception as e:
            logger.error(f"[Firecrawl] Extraction failed: {e}")
            return None

    async def map_site(self, url: str) -> List[str]:
        """Discover all URLs on a site structure."""
        if not self.enabled:
            return []
            
        logger.info(f"[Firecrawl] Mapping site: {url}")
        try:
            result = self._app.map_url(url)
            return result.get("links", [])
        except Exception as e:
            logger.error(f"[Firecrawl] Map failed for {url}: {e}")
            return []

    async def crawl(self, url: str, limit: int = 10) -> Optional[Dict[str, Any]]:
        """Crawl a site asynchronously."""
        if not self.enabled:
            return None
            
        logger.info(f"[Firecrawl] Starting crawl: {url} (limit={limit})")
        try:
            # This returns a job ID; we'd need to poll in a real implementation
            # or use the wait_until_done parameter if supported by SDK.
            result = self._app.crawl_url(url, params={"limit": limit, "scrapeOptions": {"formats": ["markdown"]}})
            return result
        except Exception as e:
            logger.error(f"[Firecrawl] Crawl failed for {url}: {e}")
            return None

    async def close(self):
        """Cleanup (Firecrawl SDK handles its own sessions)."""
        pass
