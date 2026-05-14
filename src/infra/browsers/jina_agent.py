"""
 ╔══════════════════════════════════════════════════════════════════════════╗
 ║  infra/browsers/jina_agent.py                                             ║
 ║                                                                          ║
 ║  Role: High-Speed Markdown Reader (Jina AI Reader).                       ║
 ║  Used for fast, LLM-friendly extraction from direct URLs.                ║
 ╚══════════════════════════════════════════════════════════════════════════╝
 """

from __future__ import annotations
import httpx
import asyncio
from typing import Optional, Dict, Any
from core import config
from agents.base_agent import BaseBrowserAgent
from core.logger import get_logger

logger = get_logger(__name__)

class JinaAgent(BaseBrowserAgent):
    """
    Agent using Jina Reader (r.jina.ai) to extract markdown from URLs.
    Stateless, fast, and bypasses many simple WAFs.
    """
    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self.base_url = "https://r.jina.ai/"
        self._last_content: str = ""
        self.timeout = 30
        # Jina can be disabled by config.
        self.enabled = bool(getattr(config, "JINA_ENABLED", True))


    async def is_alive(self) -> bool:
        """Jina is a stateless API, so it is always 'alive' unless disabled by credits."""
        return self.enabled

    async def start(self) -> None:
        """No-op for Jina as it's a stateless API."""
        logger.info("[Jina] Reader initialized (Stateless).")
        return

    async def close(self) -> None:
        """No-op for Jina."""
        pass

    async def get_page_source(self) -> str:
        """Returns the last retrieved markdown content."""
        return self._last_content

    async def goto_url(self, url: str) -> bool:
        """
        Fetch a URL via Jina Reader.
        """
        if url.startswith("http://") or url.startswith("https://"):
            target_url = f"{self.base_url}{url}"
        else:
            target_url = f"{self.base_url}{url}"

        headers = {
            "Accept": "text/event-stream", # Or text/plain for simple markdown
        }

        # Add API key if present in config
        api_key = getattr(config, "JINA_API_KEY", None)
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        logger.info(f"[Jina] Reading: {url}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(target_url, headers=headers)
                
                # Validation standard des erreurs
                if response.status_code == 402:
                    logger.error("[Jina] 🛑 CRÉDITS ÉPUISÉS (Statut 402).")
                    await self.report_proxy_error(url, 402)
                    self.enabled = False
                    return False
                
                if response.status_code == 403:
                    logger.warning(f"[Jina] 🛑 BLOCAGE DÉTECTÉ (403) pour {url}")
                    await self.report_proxy_error(url, 403)
                    return False

                if response.status_code == 200:
                    self._last_content = response.text
                    
                    # Check for WAF content blocks in the markdown
                    if self.is_block_response(self._last_content):
                        logger.warning(f"[Jina] 🛑 BLOCAGE DÉTECTÉ (Contenu) pour {url}")
                        await self.report_proxy_error(url, 403)
                        return False
                        
                    return True
                else:
                    logger.error(f"[Jina] Failed with status {response.status_code}")
                    await self.report_proxy_error(url, response.status_code)
                    return False
        except Exception as e:
            logger.error(f"[Jina] Error fetching {url}: {e}")
            return False

    async def crawl_website(self, url: str, **kwargs) -> str:
        """
        Simple 'crawl' for Jina: just read the main URL.
        Jina Reader is designed to extract the meat of a single page.
        """
        if await self.goto_url(url):
            return self._last_content
        return ""

    async def search_google_ai_mode(self, prompt: str, **kwargs) -> Optional[str]:
        """Utilise le endpoint de recherche natif de Jina AI (s.jina.ai)."""
        ai_mode_url = kwargs.get("ai_mode_url")
        row = kwargs.get("row")
        from common.search_engine import extract_search_terms
        search_query = extract_search_terms(prompt)

        # Si un ai_mode_url est fourni, on l'utilise directement
        if ai_mode_url:
            import urllib.parse
            url = ai_mode_url + urllib.parse.quote_plus(search_query)
            logger.info(f"[Jina] Reading direct AI Mode URL: {url}")
            if await self.goto_url(url):
                return self._last_content
            return None

        search_url = f"https://s.jina.ai/{urllib.parse.quote(search_query)}"
        headers = {"Accept": "text/plain"}
        
        api_key = getattr(config, "JINA_API_KEY", None) or __import__("os").getenv("JINA_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        logger.info(f"[Jina] Recherche via s.jina.ai: {search_query}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(search_url, headers=headers)
                
                if response.status_code == 402:
                    logger.error("[Jina] 🛑 CRÉDITS ÉPUISÉS (Statut 402).")
                    await self.report_proxy_error(search_url, 402)
                    self.enabled = False
                    return None
                    
                if response.status_code == 403:
                    logger.warning(f"[Jina] 🛑 BLOCAGE DÉTECTÉ (403) via s.jina.ai")
                    await self.report_proxy_error(search_url, 403)
                    return None

                if response.status_code == 200:
                    content = response.text
                    if self.is_block_response(content):
                        logger.warning(f"[Jina] 🛑 BLOCAGE DÉTECTÉ (Contenu) via s.jina.ai")
                        await self.report_proxy_error(search_url, 403)
                        return None
                    return content
                else:
                    logger.error(f"[Jina] Echec de la recherche (statut {response.status_code})")
                    await self.report_proxy_error(search_url, response.status_code)
                    return None
        except Exception as e:
            logger.error(f"[Jina] Erreur de recherche: {e}")
            return None

    async def search_google_ai(self, prompt: str, **kwargs) -> Optional[str]:
        """Fallback transparent vers la recherche Jina."""
        return await self.search_google_ai_mode(prompt, **kwargs)

    async def search_google_ai_interactive(self, prompt: str, **kwargs) -> Optional[str]:
        """Interactive search fallback for Jina."""
        return await self.search_google_ai_mode(prompt, **kwargs)

    async def submit_google_search(self, prompt: str) -> bool:
        """Jina est une API REST (Stateless), il n'y a pas de formulaire à soumettre."""
        return False

    async def rotate_proxy(self) -> None:
        """Jina gère sa propre infrastructure et rotation d'IP en interne."""
        pass
