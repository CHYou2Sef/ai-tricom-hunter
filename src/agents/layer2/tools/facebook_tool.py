"""
Layer 2 — LangChain Tool: Facebook Phone Extractor

Scrapes a public Facebook business page (no login required)
using the facebook-scraper library.  Respects ToS by only
accessing public pages and never posting or modifying data.

Install: pip install facebook-scraper
"""
import re
import asyncio
from typing import Optional

try:
    from langchain.tools import BaseTool
except ImportError:
    # Graceful fallback before langchain is installed
    class BaseTool:  # type: ignore[no-redef]
        name: str = ""
        description: str = ""
        def _run(self, *a, **kw): raise NotImplementedError
        async def _arun(self, *a, **kw): raise NotImplementedError

from core.logger import get_logger

logger = get_logger(__name__)


class FacebookPhoneTool(BaseTool):
    """Extract phone number from a public Facebook business page URL."""

    name: str        = "facebook_phone_extractor"
    description: str = (
        "Extract phone number from a public Facebook business page URL. "
        "Input must be a full Facebook URL like https://facebook.com/company-name."
    )

    def _run(self, url: str) -> dict:
        """Synchronous scrape via facebook-scraper library."""
        try:
            from facebook_scraper import get_profile
        except ImportError:
            logger.warning("[FacebookTool] facebook-scraper not installed — pip install facebook-scraper")
            return {"error": "facebook-scraper not installed", "url": url}

        slug_match = re.search(r"facebook\.com/([^/?#]+)", url)
        if not slug_match:
            return {"error": "Cannot parse Facebook slug from URL", "url": url}

        slug = slug_match.group(1).rstrip("/")
        try:
            profile = get_profile(
                slug,
                options={
                    "posts":     False,
                    "friends":   False,
                    "followers": False,
                    "likes":     False,
                    "limit":     0,
                },
            )
            phone: Optional[str] = profile.get("phone") or profile.get("public_phone")
            return {
                "phone":  phone,
                "about":  profile.get("bio", ""),
                "source": "facebook_scraper",
                "url":    url,
            }
        except Exception as exc:
            logger.warning(f"[FacebookTool] {url}: {exc}")
            return {"error": str(exc), "url": url}

    async def _arun(self, url: str) -> dict:
        """Async wrapper — runs synchronous scrape in a thread pool."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self._run, url)
