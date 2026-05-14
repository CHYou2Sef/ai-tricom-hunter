"""
╔══════════════════════════════════════════════════════════════════════════╗
║  infra/browsers/firecrawl_agent.py                                        ║
║                                                                          ║
║  Role: Premium Managed Scraper (Firecrawl SDK).                          ║
║  Used for hard-to-scrape sites, structured extraction, and mass crawls.  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
import os
import asyncio
from typing import Optional, Dict, Any, List
from firecrawl import FirecrawlApp
from core import config
from agents.base_agent import BaseBrowserAgent
from core.logger import get_logger

logger = get_logger(__name__)

class FirecrawlAgent(BaseBrowserAgent):
    """
    Wrapper for the Firecrawl SDK.
    Provides high-level methods for scraping, crawling, and AI-powered extraction.
    """
    def __init__(self, worker_id: int = 0, api_key: Optional[str] = None):
        super().__init__(worker_id)
        self.api_key = api_key or config.FIRECRAWL_API_KEY
        self.enabled = config.FIRECRAWL_ENABLED and bool(self.api_key)
        self._app = None
        self._last_content: str = ""
        self._lock = asyncio.Lock()
        
        if self.enabled:
            try:
                self._app = FirecrawlApp(api_key=self.api_key)
                logger.info("[Firecrawl] SDK initialized.")
            except Exception as e:
                logger.error(f"[Firecrawl] Failed to initialize: {e}")
                self.enabled = False
        
    async def start(self):
        """No-op for Firecrawl SDK as it's stateless."""
        return True

    async def is_alive(self) -> bool:
        """Check if the agent is enabled and active."""
        return self.enabled

    async def get_page_source(self) -> str:
        """Returns the last scraped markdown content."""
        return self._last_content

    async def goto_url(self, url: str) -> bool:
        """
        Fetch a URL via Firecrawl scrape.
        """
        params = {
            "formats": ["markdown"],
            "only_main_content": False
        }
        
        logger.info(f"[Firecrawl] Navigating to: {url}")
        result = await self.scrape(url, params=params)
        if result and isinstance(result, dict):
            content = result.get('markdown') or result.get('content') or ""
            if self.is_block_response(content):
                logger.warning(f"[Firecrawl] 🛡️ Block detected on {url}")
                await self.report_proxy_error("firecrawl_api", 403)
                return False
                
            async with self._lock:
                self._last_content = content
                return bool(self._last_content)
        return False

    async def scrape(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Scrape a single URL to Markdown/HTML."""
        if not self.enabled or not self._app:
            return None
            
        logger.info(f"[Firecrawl] Scraping: {url}")
        try:
            result = await asyncio.to_thread(self._app.scrape_url, url, params=(params or {}))
            return result
        except Exception as e:
            err_msg = str(e)
            if "Insufficient credits" in err_msg or "Payment Required" in err_msg or "402" in err_msg:
                logger.error("[Firecrawl] 🛑 CRÉDITS ÉPUISÉS. Impossible de scraper.")
                await self.report_proxy_error("firecrawl_api", 402)
                self.enabled = False
            elif "403" in err_msg or "blocked" in err_msg.lower():
                await self.report_proxy_error("firecrawl_api", 403)
            else:
                logger.error(f"[Firecrawl] Scrape failed for {url}: {e}")
            return None

    async def extract(self, urls: List[str], prompt: str, schema: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """
        AI-powered structured extraction from one or more URLs.
        """
        if not self.enabled or not self._app:
            return None
            
        logger.info(f"[Firecrawl] Extracting from {len(urls)} URLs...")
        try:
            result = await asyncio.to_thread(self._app.extract, urls, {"prompt": prompt, "schema": schema})
            return result
        except Exception as e:
            logger.error(f"[Firecrawl] Extraction failed: {e}")
            return None

    async def map_site(self, url: str) -> List[str]:
        """Discover all URLs on a site structure."""
        if not self.enabled or not self._app:
            return []
            
        logger.info(f"[Firecrawl] Mapping site: {url}")
        try:
            result = await asyncio.to_thread(self._app.map_url, url)
            return result.get("links", [])
        except Exception as e:
            logger.error(f"[Firecrawl] Map failed for {url}: {e}")
            return []

    async def crawl_website(self, url: str, **kwargs) -> str:
        """Crawl a site asynchronously and return combined markdown."""
        if not self.enabled or not self._app:
            return ""
            
        logger.info(f"[Firecrawl] Starting crawl: {url}")
        try:
            # Note: Firecrawl crawl is asynchronous, but we wait for it here
            # for simpler integration with the waterfall.
            result = await asyncio.to_thread(
                self._app.crawl_url, 
                url, 
                params={"limit": 5, "scrapeOptions": {"formats": ["markdown"]}}
            )
            
            if result and isinstance(result, dict) and 'data' in result:
                pages = result['data']
                combined = []
                for p in pages:
                    content = p.get('markdown') or p.get('content') or ""
                    if content:
                        combined.append(f"--- PAGE: {p.get('url')} ---\n{content}")
                
                self._last_content = "\n\n".join(combined)
                return self._last_content
            
            return ""
        except Exception as e:
            err_msg = str(e)
            if "Insufficient credits" in err_msg or "Payment Required" in err_msg:
                logger.error("[Firecrawl] 🛑 CRÉDITS ÉPUISÉS. Impossible de crawler.")
                self.enabled = False
            else:
                logger.error(f"[Firecrawl] Crawl failed for {url}: {e}")
            return ""

    async def close(self):
        """Cleanup (Firecrawl SDK handles its own sessions)."""
        pass

    # ── Stub methods for BaseBrowserAgent contract ─────────────────────────

    async def search_google_ai_mode(self, prompt: str, **kwargs) -> Optional[str]:
        """Adaptateur pour la recherche Google via Firecrawl."""
        ai_mode_url = kwargs.get("ai_mode_url")
        row = kwargs.get("row")
        if not self.enabled or not self._app:
            return None

        from common.search_engine import extract_search_terms
        search_query = extract_search_terms(prompt)

        if ai_mode_url:
            import urllib.parse
            url = ai_mode_url + urllib.parse.quote_plus(search_query)
            logger.info(f"[Firecrawl] Scraping direct AI Mode URL: {url}")
            await self.goto_url(url)
            return self._last_content

        logger.info(f"[Firecrawl] Recherche via endpoint natif: {search_query}")
        try:
            search_result = await asyncio.to_thread(self._app.search, search_query)
            
            if search_result and isinstance(search_result, list):
                markdown_results = []
                for item in search_result:
                    title = item.get('title', 'N/A')
                    snippet = item.get('description', item.get('snippet', ''))
                    url = item.get('url', '')
                    markdown_results.append(f"### {title}\nURL: {url}\n{snippet}")
                
                async with self._lock:
                    self._last_content = "\n\n".join(markdown_results)
                    
                if self.is_block_response(self._last_content):
                    logger.warning("[Firecrawl] 🛡️ Block detected in search results.")
                    return None
                    
                return self._last_content
            return None
        except Exception as e:
            err_msg = str(e)
            if "Insufficient credits" in err_msg or "Payment Required" in err_msg:
                logger.error("[Firecrawl] 🛑 CRÉDITS ÉPUISÉS. Désactivation de l'agent pour cette session.")
                self.enabled = False
            else:
                logger.error(f"[Firecrawl] Native search failed: {e}")
            return None

    async def search_google_ai(self, prompt: str, **kwargs) -> Optional[str]:
        return await self.search_google_ai_mode(prompt, **kwargs)

    async def search_google_ai_interactive(self, prompt: str, **kwargs) -> Optional[str]:
        """Interactive search fallback for Firecrawl."""
        return await self.search_google_ai_mode(prompt, **kwargs)

    async def submit_google_search(self, prompt: str) -> bool:
        """Pas de session interactive pour soumettre un formulaire."""
        return False

    async def rotate_proxy(self) -> None:
        """Firecrawl gère sa propre rotation d'IP."""
        pass
