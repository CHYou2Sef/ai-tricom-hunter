"""
 ╔══════════════════════════════════════════════════════════════════════════╗
 ║  infra/browsers/jina_agent.py                                             ║
 ║                                                                          ║
 ║  Role: High-Speed Markdown Reader (Jina AI Reader).                       ║
 ║  Used for fast, LLM-friendly extraction from direct URLs.                ║
 ╚══════════════════════════════════════════════════════════════════════════╝
 """

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
                if response.status_code == 200:
                    self._last_content = response.text
                    return True
                elif response.status_code == 402:
                    logger.error("[Jina] 🛑 CRÉDITS ÉPUISÉS (Statut 402). Veuillez recharger votre compte sur https://jina.ai")
                    return False
                else:
                    logger.error(f"[Jina] Failed with status {response.status_code}")
                    return False
        except Exception as e:
            logger.error(f"[Jina] Error fetching {url}: {e}")
            return False

    async def crawl_website(self, url: str) -> str:
        """
        Simple 'crawl' for Jina: just read the main URL.
        Jina Reader is designed to extract the meat of a single page.
        """
        if await self.goto_url(url):
            return self._last_content
        return ""

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """Utilise le endpoint de recherche natif de Jina AI (s.jina.ai)."""
        import urllib.parse
        import re

        # Si le prompt est un prompt complexe (AI Mode), on extrait les termes essentiels
        # pour éviter l'erreur 422 (URL trop longue) et obtenir de meilleurs résultats.
        search_query = prompt
        if len(prompt) > 200 or "###" in prompt:
            name_match = re.search(r"NAME:\s*(.*)", prompt)
            addr_match = re.search(r"ADDRESS:\s*(.*)", prompt)
            if name_match:
                search_query = name_match.group(1).strip()
                if addr_match:
                    # On ne garde que la ville/code postal si possible pour la recherche
                    addr = addr_match.group(1).strip()
                    search_query += f" {addr}"
            else:
                # Fallback: on prend juste les 150 premiers caractères
                search_query = prompt[:150]

        search_url = f"https://s.jina.ai/{urllib.parse.quote(search_query)}"
        headers = {"Accept": "text/plain"}
        
        api_key = getattr(config, "JINA_API_KEY", None) or __import__("os").getenv("JINA_API_KEY")
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        logger.info(f"[Jina] Recherche via s.jina.ai: {search_query}")
        try:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                response = await client.get(search_url, headers=headers)
                if response.status_code == 200:
                    return response.text
                elif response.status_code == 402:
                    logger.error("[Jina] 🛑 CRÉDITS ÉPUISÉS (Statut 402). La recherche est désactivée jusqu'au rechargement.")
                    return None
                else:
                    logger.error(f"[Jina] Echec de la recherche (statut {response.status_code})")
                    return None
        except Exception as e:
            logger.error(f"[Jina] Erreur de recherche: {e}")
            return None

    async def search_google_ai(self, query: str) -> Optional[str]:
        """Fallback transparent vers la recherche Jina."""
        return await self.search_google_ai_mode(query)

    async def submit_google_search(self, query: str) -> bool:
        """Jina est une API REST (Stateless), il n'y a pas de formulaire à soumettre."""
        return False

    async def rotate_proxy(self) -> None:
        """Jina gère sa propre infrastructure et rotation d'IP en interne."""
        pass
