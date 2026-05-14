"""
╔══════════════════════════════════════════════════════════════════════════╗
║  infra/scrapers/agent_scraper.py                                         ║
║                                                                          ║
║  Scrapy Sniper — post-discovery bonus step.                              ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Fires ONLY after a browser tier has found a target website URL        ║
║    but failed to extract the phone number from the rendered page.        ║
║    Uses Scrapy's lightweight HTTP client to parse static HTML directly.  ║
║                                                                          ║
║  REACTOR FIX (root cause of "installed reactor does not match"):         ║
║    crochet.setup() installs and manages the Twisted reactor in its own   ║
║    background thread. Importing `from twisted.internet import reactor`   ║
║    explicitly AFTER that point forces a second reactor installation that ║
║    conflicts with the one crochet already set up.                        ║
║    Solution: never import reactor directly — let crochet own it.         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import asyncio
import json
import logging

# ── FIX: Initialize crochet FIRST — before any Scrapy/Twisted imports ────────
# crochet.setup() installs the Twisted reactor in a dedicated background
# thread and patches the event loop bridge.  Anything that imports
# twisted.internet.reactor AFTER this point will use the one crochet
# already installed, preventing "reactor mismatch" errors.
import crochet
crochet.setup()

# ── Scrapy imports (AFTER crochet.setup) ─────────────────────────────────────
# DO NOT import `from twisted.internet import reactor` — crochet owns it.
import scrapy
from scrapy.crawler import CrawlerRunner
from scrapy.signalmanager import dispatcher
from scrapy import signals

logger = logging.getLogger(__name__)

# ── Hard-coded B2B fallback selectors ────────────────────────────────────────
FALLBACK_SELECTORS = {
    "phone": [
        "a[href^='tel:']::text",
        ".contact-phone::text",
        "span:contains('Tél')::text",
        "p:contains('Tél')::text",
        ".phone::text",
        "[itemprop='telephone']::text",
    ],
    "email": [
        "a[href^='mailto:']::text",
        ".contact-email::text",
    ],
    "siren": [
        "span:contains('SIREN')::text",
        "p:contains('SIRET')::text",
    ],
}


class GenericSpider(scrapy.Spider):
    name = "generic_spider"

    def __init__(self, url=None, extraction_rules=None, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.start_urls = [url] if url else []
        self.extraction_rules = json.loads(extraction_rules) if extraction_rules else {}
        self.results = []

    def parse(self, response):
        item = {}

        # 1. Try LLM-generated dynamic rules first
        for field, selector in self.extraction_rules.items():
            value = response.css(selector).get()
            if value:
                item[field] = value.strip()

        # 2. Fill missing fields using hardcoded B2B fallbacks
        for field, selectors in FALLBACK_SELECTORS.items():
            if not item.get(field):
                for sel in selectors:
                    val = response.css(sel).get()
                    if val:
                        item[field] = val.strip()
                        break

        # 3. If nothing found, save raw HTML for LLM fallback processing
        if not item:
            item["_raw_html"] = response.text[:8000]

        self.results.append(item)
        yield item


@crochet.wait_for(timeout=30.0)
def _run_spider_crochet(url: str, extraction_rules: dict, results_list: list):
    """
    Run the Scrapy spider via crochet's blocking bridge.

    crochet.wait_for turns this into a synchronous call that blocks the
    calling thread (not the asyncio event loop) until the spider finishes.

    IMPORTANT: We connect/disconnect the item_scraped signal INSIDE this
    function on every call to prevent signal handler accumulation across
    multiple invocations (which would cause duplicate items in results_list).
    """
    def _on_item_scraped(item, response, spider):
        results_list.append(dict(item))

    # Connect signal for this specific run
    dispatcher.connect(_on_item_scraped, signal=signals.item_scraped)

    scrapy_settings = {
        "USER_AGENT": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_TIMEOUT": 15,
        "LOG_LEVEL": "WARNING",
        "AUTOTHROTTLE_ENABLED": True,
        "AUTOTHROTTLE_START_DELAY": 1,
        "AUTOTHROTTLE_MAX_DELAY": 10,
        "CONCURRENT_REQUESTS": 1,  # Sniper mode — one request at a time
        # ── REACTOR NOTE ────────────────────────────────────────────────────
        # Do NOT set TWISTED_REACTOR here.  crochet already installed a
        # reactor; overriding it would trigger:
        #   "installed reactor (X) does not match requested reactor (Y)"
    }

    runner = CrawlerRunner(scrapy_settings)

    def _deferred_with_cleanup():
        """Crawl then disconnect signal to prevent listener accumulation."""
        d = runner.crawl(
            GenericSpider,
            url=url,
            extraction_rules=json.dumps(extraction_rules),
        )

        def _cleanup(result):
            try:
                dispatcher.disconnect(_on_item_scraped, signal=signals.item_scraped)
            except Exception:
                pass
            return result

        d.addBoth(_cleanup)
        return d

    return _deferred_with_cleanup()


async def run_ai_spider(url: str, selectors: dict = None) -> dict:
    """
    Async wrapper: run the Scrapy Sniper inside the HybridEngine waterfall.

    Uses asyncio.to_thread so the blocking @crochet.wait_for call does not
    freeze the asyncio event loop.  The results list is mutated via the
    item_scraped signal handler inside _run_spider_crochet.
    """
    if not url or not url.strip():
        logger.warning("[Scrapy Sniper] Empty URL — skipping.")
        return {}

    results: list = []
    try:
        await asyncio.to_thread(_run_spider_crochet, url.strip(), selectors or {}, results)

        if results:
            logger.info(f"[Scrapy Sniper] ✅ Extracted {len(results)} item(s) from {url}")
            return results[0]

        logger.debug(f"[Scrapy Sniper] No data extracted from {url}")
    except crochet.TimeoutError:
        logger.warning(f"[Scrapy Sniper] ⏰ Spider timed out (30s) for {url}")
    except Exception as exc:
        logger.error(f"[Scrapy Sniper] ❌ Error during execution for {url}: {exc}")

    return {}
