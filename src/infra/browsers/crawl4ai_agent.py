"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/crawl4ai_agent.py                                               ║
║                                                                          ║
║  TASK 1 from GEMINI.md — Tier 3: Managed Async Scraper                  ║
║                                                                          ║
║  Uses Crawl4AI (free, open-source) as the hardened Tier 3 engine.       ║
║  This replaces Firecrawl with a zero-cost, self-hosted solution.         ║
║                                                                          ║
║  Crawl4AI advantages:                                                    ║
║    ✓ Full JS rendering (Chromium-based)                                  ║
║    ✓ LLM-ready Markdown output                                           ║
║    ✓ Handles AJAX, SPA, and infinite scroll                              ║
║    ✓ Smart content extraction (no boilerplate)                           ║
║    ✓ No API key required — runs fully locally                            ║
║    ✓ Rate-limit aware with automatic backoff                             ║
║                                                                          ║
║  Install: pip install crawl4ai                                           ║
║           crawl4ai-setup  (downloads Chromium)                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import re
from typing import Optional, List

from core import config
from core.logger import get_logger, alert

logger = get_logger(__name__)


from agents.base_agent import BaseBrowserAgent

class Crawl4AIAgent(BaseBrowserAgent):
    """
    Tier 3 scraper built on Crawl4AI (https://github.com/unclecode/crawl4ai).

    This agent is routed to by HybridEngine when:
      - A Tier 1/2 escalation has already failed, OR
      - The target URL matches config.HYBRID_TIER3_DOMAINS

    It returns clean Markdown content suitable for LLM extraction.
    """

    def __init__(self):
        super().__init__()
        self._crawler = None

    async def get_page_source(self) -> str:
        """Returns the last scraped markdown content for UUE parsing."""
        return getattr(self, "_last_content", "")

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """
        Initialise the Crawl4AI crawler instance.
        Reuses a single crawler to share the browser process.
        """
        try:
            from crawl4ai import AsyncWebCrawler  # type: ignore
        except ImportError:
            raise RuntimeError(
                "crawl4ai is not installed.\n"
                "Run: pip install crawl4ai && crawl4ai-setup"
            )

        logger.info("[Crawl4AI] 🕷️  Initialising Tier 3 crawler...")
        
        from crawl4ai import BrowserConfig, CrawlerRunConfig  # type: ignore
        browser_cfg = BrowserConfig(
            headless=True,
            extra_args=["--no-sandbox"] if not config.BROWSER_USE_SANDBOX else []
        )
        self._crawler = AsyncWebCrawler(config=browser_cfg)
        await self._crawler.__aenter__()
        alert("INFO", "Crawl4AI session started")
        logger.info("[Crawl4AI] ✅ Ready.")

    async def close(self) -> None:
        """Release Crawl4AI resources."""
        try:
            if self._crawler:
                await self._crawler.__aexit__(None, None, None)
        except Exception:
            pass
        finally:
            self._crawler = None
            logger.info("[Crawl4AI] Crawler closed.")

    # ─────────────────────────────────────────────────────────────────
    # SCRAPING METHODS
    # ─────────────────────────────────────────────────────────────────

    async def scrape(self, url: str) -> Optional[str]:
        """
        Scrape a URL and return clean Markdown content.

        Handles:
          - JavaScript-heavy pages (waits for full render)
          - 429 rate-limits (3-attempt backoff: 5s → 15s → 30s)
          - Empty results → returns None

        Args:
            url : Target URL to scrape

        Returns:
            str  : Clean Markdown content
            None : On unrecoverable failure
        """
        if not self._crawler:
            logger.warning("[Crawl4AI] Not started. Call start() first.")
            return None

        backoff_delays = [5, 15, 30]

        for attempt, delay in enumerate(backoff_delays, start=1):
            try:
                logger.info(f"[Crawl4AI] Scraping (attempt {attempt}/3): {url}")
                result = await self._crawler.arun(
                    url=url,
                    word_count_threshold=10,          # Skip near-empty pages
                    exclude_external_links=True,      # Keep content focused
                    remove_overlay_elements=True,     # Strip cookie banners etc.
                    bypass_cache=True,                # Always fresh content
                )

                if result.success and result.markdown:
                    content = result.markdown.strip()
                    logger.info(
                        f"[Crawl4AI] ✅ Got {len(content)} chars from {url}"
                    )
                    return content

                # Empty result — check for rate-limiting signals
                if result.status_code in (429, 403):
                    alert("WARN", f"Crawl4AI rate-limited (HTTP {result.status_code})",
                          {"url": url, "retry_in": f"{delay}s"})
                    await asyncio.sleep(delay)
                    continue

                logger.warning(f"[Crawl4AI] Empty result for {url} (status={result.status_code})")
                return None

            except Exception as exc:
                logger.error(f"[Crawl4AI] Attempt {attempt} failed: {exc}")
                if attempt < len(backoff_delays):
                    await asyncio.sleep(delay)
                    continue
                return None

        logger.error(f"[Crawl4AI] All attempts exhausted for {url}")
        alert("CRITICAL", "Crawl4AI: all retry attempts failed",
              {"url": url, "attempts": len(backoff_delays)})
        return None

    async def crawl_website(self, base_url: str, max_pages: int = 3) -> str:
        """
        Deep-crawl a website: homepage + up to max_pages sub-pages.
        Follows contact/about links just like the PatchrightAgent.

        Args:
            base_url  : Root URL of the target website
            max_pages : Maximum number of sub-pages to visit

        Returns:
            Concatenated Markdown content from all visited pages.
        """
        all_content: List[str] = []

        # ── Scrape homepage ────────────────────────────────────────
        homepage = await self.scrape(base_url)
        if homepage:
            all_content.append(f"## {base_url}\n\n{homepage}")

        # ── Discover and visit contact/about pages ─────────────────
        sub_urls = self._extract_contact_links(homepage or "", base_url)
        for url in sub_urls[:max_pages - 1]:
            sub_content = await self.scrape(url)
            if sub_content:
                all_content.append(f"\n## {url}\n\n{sub_content}")
            await asyncio.sleep(1.5)  # Polite crawl delay

        return "\n\n---\n\n".join(all_content)

    async def search_google_ai(self, query: str) -> Optional[str]:
        """
        Use Crawl4AI to scrape Google AI Mode results for a query.
        This is the Tier 3 equivalent of PlaywrightAgent.search_google_ai_mode().

        Returns extracted page text for downstream enrichment.
        """
        from common.search_engine import generate_google_ai_url
        url = generate_google_ai_url(query)
        logger.info(f"[Crawl4AI] 🔍 Google AI Mode scrape: {query}")
        return await self.scrape(url)

    async def search_google_ai_mode(self, query: str) -> Optional[str]:
        """Alias for search_google_ai (scrape) to maintain HybridEngine compatibility."""
        return await self.search_google_ai(query)

    async def submit_google_search(self, query: str) -> bool:
        """
        Crawl4AI implementation of submit_google_search.
        """
        import urllib.parse
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(query)}"
        logger.info(f"[Crawl4AI] 🔍 Google Search (submit): {query}")
        content = await self.scrape(url)
        # Store for extraction
        self._last_content = content
        if content and len(content) > 200:
            logger.info(f"[Crawl4AI] ✅ submit_google_search — {len(content)} chars.")
            return True
        logger.warning("[Crawl4AI] submit_google_search — empty or blocked response.")
        return False

    async def goto_url(self, url: str) -> bool:
        """
        Managed navigation for Tier 3. 
        Stores the result internally for use by get_page_source().
        """
        content = await self.scrape(url)
        self._last_content = content
        return bool(content)

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        """
        Crawl4AI doesn't support interactive chat easily. 
        Escalating to next tier if Tier 3 cannot perform this.
        """
        logger.warning("[Crawl4AI] search_gemini_ai not supported in Managed Scraper mode. Escalating.")
        return None


    # ─────────────────────────────────────────────────────────────────
    # HELPERS
    # ─────────────────────────────────────────────────────────────────

    @staticmethod
    def _extract_contact_links(markdown_content: str, base_url: str) -> List[str]:
        """
        Find contact/about page URLs from Markdown content.
        Crawl4AI formats links as [text](url) in its Markdown output.

        Returns a list of absolute URLs matching contact keywords.
        """
        found: List[str] = []
        # Match Markdown links: [text](url)
        link_pattern = re.compile(r'\[([^\]]*)\]\((https?://[^)]+)\)')

        for match in link_pattern.finditer(markdown_content):
            text = match.group(1).lower()
            url  = match.group(2)
            if any(k in text or k in url.lower() for k in config.CONTACT_KEYWORDS):
                if url not in found:
                    found.append(url)

        return found
