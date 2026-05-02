"""
Layer 2 — LangChain Tool: Generic Website Phone Extractor

Scrapes the company homepage + common contact sub-pages using
httpx (async-ready, fast) and BeautifulSoup.

Strategy:
  1. Try homepage (/)
  2. Try /contact, /about, /mentions-legales, /a-propos, /nous-contacter
  3. On each page: run existing extract_phones() pipeline
  4. Return on first valid phone found

Phone extraction re-uses the existing extractor so the blocklist,
phonenumbers validation, and normalisation chain are automatically applied.
"""
import asyncio

import httpx
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
from core import config
from core.logger import get_logger

logger = get_logger(__name__)

# Common French B2B contact page slugs (from config.CONTACT_KEYWORDS)
_CONTACT_SLUGS = [
    "contact", "nous-contacter", "contactez-nous",
    "about", "a-propos", "qui-sommes-nous",
    "mentions-legales", "legal", "informations-legales",
]

_CLIENT_HEADERS = {
    "User-Agent":      "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0",
    "Accept-Language": "fr-FR,fr;q=0.9",
}


class WebsitePhoneTool(BaseTool):
    """Scrape a company website home + contact pages to find a phone number."""

    name: str        = "website_phone_extractor"
    description: str = (
        "Scrape a company website to find a phone number. "
        "Input must be a full URL including https://."
    )

    def _run(self, url: str) -> dict:
        """
        Synchronous multi-page scrape.
        Tries homepage first, then up to 3 contact sub-pages.
        """
        base        = url.rstrip("/")
        targets     = [base] + [f"{base}/{slug}" for slug in _CONTACT_SLUGS[:3]]
        pages_tried = []
        found_phone = None

        try:
            with httpx.Client(
                timeout=10,
                follow_redirects=True,
                headers=_CLIENT_HEADERS,
            ) as client:
                for target in targets:
                    try:
                        resp = client.get(target)
                        if resp.status_code not in (200, 203):
                            continue
                        text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True)
                        pages_tried.append(target)

                        phones = extract_phones(text, source_label="website_direct")
                        phone  = get_best_phone(phones)
                        if phone:
                            found_phone = phone
                            logger.info(f"[WebsiteTool] ✅ Phone found on {target}")
                            break

                    except (httpx.ConnectError, httpx.ReadTimeout, httpx.RemoteProtocolError):
                        continue  # Skip unreachable sub-pages silently

        except Exception as exc:
            logger.warning(f"[WebsiteTool] {url}: {exc}")
            return {"error": str(exc), "url": url}

        return {
            "phone":       found_phone,
            "pages_tried": pages_tried,
            "source":      "website_direct",
            "url":         url,
        }

    async def _arun(self, url: str) -> dict:
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run, url)
