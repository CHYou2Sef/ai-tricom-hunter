"""
Layer 2 — LangChain Tool: LinkedIn Phone Extractor

Scrapes the public /about page of a LinkedIn company profile
using requests + BeautifulSoup (no login, no API key).

LinkedIn public /about pages expose:
  - Company description
  - Website link
  - Occasionally phone numbers in the description text

Phone extraction is delegated to the existing extract_phones() pipeline
so blocklist + phonenumbers validation are automatically applied.
"""
import asyncio

import requests
from bs4 import BeautifulSoup

try:
    from langchain.tools import BaseTool
except ImportError:
    class BaseTool:  # type: ignore[no-redef]
        name: str = ""
        description: str = ""
        def _run(self, *a, **kw): raise NotImplementedError
        async def _arun(self, *a, **kw): raise NotImplementedError

from domain.search.phone_extractor import extract_phones, get_best_phone
from core.logger import get_logger

logger = get_logger(__name__)

_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Accept":          "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}


class LinkedInPhoneTool(BaseTool):
    """Extract phone number from a public LinkedIn company /about page."""

    name: str        = "linkedin_phone_extractor"
    description: str = (
        "Extract phone number from a public LinkedIn company page. "
        "Input must be a full LinkedIn company URL."
    )

    def _run(self, url: str) -> dict:
        """Synchronous HTTP scrape of the LinkedIn public /about page."""
        # Always target the /about sub-page which lists contact info
        if "/about" not in url:
            about_url = url.rstrip("/") + "/about/"
        else:
            about_url = url

        try:
            resp = requests.get(about_url, headers=_HEADERS, timeout=12)
            if resp.status_code != 200:
                return {"error": f"HTTP {resp.status_code}", "url": url}

            soup   = BeautifulSoup(resp.text, "html.parser")
            text   = soup.get_text(" ", strip=True)

            # Re-use the existing extractor (blocklist + phonenumbers lib)
            phones = extract_phones(text, source_label="linkedin")
            phone  = get_best_phone(phones)

            return {"phone": phone, "source": "linkedin_scraper", "url": url}

        except requests.Timeout:
            logger.warning(f"[LinkedInTool] Timeout: {url}")
            return {"error": "timeout", "url": url}
        except Exception as exc:
            logger.warning(f"[LinkedInTool] {url}: {exc}")
            return {"error": str(exc), "url": url}

    async def _arun(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run, url)
