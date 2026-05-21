"""
fast_pipeline/parallel_scraper.py - Parallel Social URL Scraping

Replaces Layer2 LangGraph with direct asyncio parallelization.
Runs Facebook/LinkedIn/Website CONCURRENTLY instead of sequentially.
"""

import asyncio
from dataclasses import dataclass, field

from core.logger import get_logger

logger = get_logger(__name__)


@dataclass
class ScraperResult:
    """Standardized result from any scraper source."""

    phone: str | None = None
    score: int = 0
    source: str = "unknown"
    raw_data: dict[str, object] = field(default_factory=dict)


class ParallelSocialScraper:
    """
    PARALLEL scraper - runs all sources simultaneously.
    Replaces sequential LangGraph Layer2 for 3-5x speed improvement.
    """

    def __init__(
        self,
        row_index: int,
        company_name: str,
        company_address: str = "",
        siren: str = "",
    ):
        self.row_index = row_index
        self.company_name = company_name
        self.company_address = company_address
        self.siren = siren
        self.errors: list[str] = []

    async def scrape_all(
        self, urls: dict[str, list[str]], timeout: float = 30.0
    ) -> list[ScraperResult]:
        """Scrape all sources IN PARALLEL using asyncio.gather."""
        tasks = []

        for source, url_list in urls.items():
            if not url_list:
                continue
            if source == "facebook":
                tasks.append(self._scrape_facebook(url_list))
            elif source == "linkedin":
                tasks.append(self._scrape_linkedin(url_list))
            elif source == "website":
                tasks.append(self._scrape_website(url_list))

        if not tasks:
            logger.debug(f"[Row {self.row_index}] No URLs to scrape")
            return []

        logger.info(f"[Row {self.row_index}] Launching {len(tasks)} parallel scrapers")

        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=timeout,
        )

        valid_results: list[ScraperResult] = []
        for r in results:
            if isinstance(r, ScraperResult):
                valid_results.append(r)
            elif isinstance(r, Exception):
                self.errors.append(str(r))
                logger.warning(f"[Row {self.row_index}] Scraper error: {r}")

        return valid_results

    async def _scrape_facebook(self, urls: list[str]) -> ScraperResult:
        """Scrape Facebook pages for phone numbers."""
        try:
            # Lazy import to avoid startup overhead
            from agents.layer2.tools.facebook_tool import scrape_facebook_pages

            text = await scrape_facebook_pages(urls, self.company_name)
            return self._extract_phone(text, "facebook", 85)
        except Exception as e:
            logger.debug(f"[FB] Error: {e}")
            return ScraperResult(source="facebook", score=0)

    async def _scrape_linkedin(self, urls: list[str]) -> ScraperResult:
        """Scrape LinkedIn pages for phone numbers."""
        try:
            from agents.layer2.tools.linkedin_tool import scrape_linkedin_pages

            text = await scrape_linkedin_pages(urls, self.company_name)
            return self._extract_phone(text, "linkedin", 88)
        except Exception as e:
            logger.debug(f"[LI] Error: {e}")
            return ScraperResult(source="linkedin", score=0)

    async def _scrape_website(self, urls: list[str]) -> ScraperResult:
        """Scrape company websites for phone numbers."""
        try:
            from agents.layer2.tools.website_tool import scrape_website_pages

            text = await scrape_website_pages(urls, self.company_name)
            return self._extract_phone(text, "website", 92)
        except Exception as e:
            logger.debug(f"[WEB] Error: {e}")
            return ScraperResult(source="website", score=0)

    def _extract_phone(self, text: str, source: str, base_score: int) -> ScraperResult:
        """Extract phone from scraped text using standard extractors."""
        if not text:
            return ScraperResult(source=source, score=0)

        from domain.search.phone_extractor import extract_phones, get_best_phone

        candidates = extract_phones(text)
        if not candidates:
            return ScraperResult(source=source, score=0)

        # get_best_phone returns a phone string (or None), not a dict.
        best: str | None = get_best_phone(candidates)
        if not best:
            return ScraperResult(source=source, score=0)

        # Keep scoring behavior deterministic without relying on a nonexistent score field.
        score = min(base_score + max(len(candidates) - 1, 0) * 5, 100)

        return ScraperResult(
            phone=best,
            score=score,
            source=source,
            raw_data={"candidates": candidates},
        )


def select_best_result(results: list[ScraperResult]) -> ScraperResult | None:
    """Select highest-scoring result from candidates."""
    if not results:
        return None
    return max(results, key=lambda r: r.score)
