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
            self._last_content = result.get('markdown') or result.get('content') or ""
            return bool(self._last_content)
        return False

    async def scrape(self, url: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        """Scrape a single URL to Markdown/HTML."""
        if not self.enabled:
            return None
            
        logger.info(f"[Firecrawl] Scraping: {url}")
        try:
            # Le SDK Firecrawl attend les options en keyword arguments, pas dans un dict 'params'
            result = self._app.scrape(url, **(params or {}))
            return result
        except Exception as e:
            err_msg = str(e)
            if "Insufficient credits" in err_msg or "Payment Required" in err_msg:
                logger.error("[Firecrawl] 🛑 CRÉDITS ÉPUISÉS. Impossible de scraper.")
                self.enabled = False
            else:
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
            # Le SDK Firecrawl attend prompt et schema en keyword arguments
            result = self._app.extract(urls, prompt=prompt, schema=schema)
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
            result = self._app.map(url)
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
            # Le SDK Firecrawl attend limit et scrape_options en keyword arguments
            result = self._app.crawl(
                url, 
                limit=limit, 
                scrape_options={"formats": ["markdown"]}
            )
            return result
        except Exception as e:
            err_msg = str(e)
            if "Insufficient credits" in err_msg or "Payment Required" in err_msg:
                logger.error("[Firecrawl] 🛑 CRÉDITS ÉPUISÉS. Impossible de crawler.")
                self.enabled = False
            else:
                logger.error(f"[Firecrawl] Crawl failed for {url}: {e}")
            return None

    async def close(self):
        """Cleanup (Firecrawl SDK handles its own sessions)."""
        pass

    # ── Stub methods for BaseBrowserAgent contract ─────────────────────────

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """Adaptateur pour la recherche Google via Firecrawl."""
        if not self.enabled:
            return None
        import urllib.parse
        import re

        # Extraction des termes de recherche essentiels (Nom + Adresse)
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

        logger.info(f"[Firecrawl] Recherche via endpoint natif: {search_query}")
        try:
            # Utilise le moteur de recherche optimisé de Firecrawl au lieu de scraper Google manuellement
            search_result = self._app.search(search_query)
            
            # On convertit les résultats en texte/markdown pour l'extracteur universel
            if search_result and isinstance(search_result, list):
                markdown_results = []
                for item in search_result:
                    title = item.get('title', 'N/A')
                    snippet = item.get('description', item.get('snippet', ''))
                    url = item.get('url', '')
                    markdown_results.append(f"### {title}\nURL: {url}\n{snippet}")
                
                self._last_content = "\n\n".join(markdown_results)
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

    async def search_google_ai(self, query: str) -> Optional[str]:
        return await self.search_google_ai_mode(query)

    async def submit_google_search(self, query: str) -> bool:
        """Pas de session interactive pour soumettre un formulaire."""
        return False

    async def rotate_proxy(self) -> None:
        """Firecrawl gère sa propre rotation d'IP."""
        pass
