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

    # ── Stub methods for BaseBrowserAgent contract ─────────────────────────

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """Jina is not a search engine."""
        return None

    async def submit_google_search(self, query: str) -> bool:
        return False

    async def rotate_proxy(self) -> None:
        pass
