import asyncio
import json
import logging
import crochet

# ── FIX: Initialize crochet BEFORE any Scrapy/Twisted imports ──
# This ensures the Twisted reactor is managed in its own background thread
# before Scrapy tries to auto-detect the asyncio loop.
crochet.setup()

import scrapy
from scrapy.crawler import CrawlerRunner
from twisted.internet import reactor
from scrapy.signalmanager import dispatcher
from scrapy import signals

logger = logging.getLogger(__name__)

# Hard-coded B2B fallback selectors
FALLBACK_SELECTORS = {
    "phone": [
        "a[href^='tel:']::text",
        ".contact-phone::text",
        "span:contains('Tél')::text",
        "p:contains('Tél')::text"
    ],
    "email": [
        "a[href^='mailto:']::text",
        ".contact-email::text"
    ],
    "siren": [
        "span:contains('SIREN')::text",
        "p:contains('SIRET')::text"
    ]
}

class GenericSpider(scrapy.Spider):
    name = "generic_spider"
    
    def __init__(self, url=None, extraction_rules=None, *args, **kwargs):
        super(GenericSpider, self).__init__(*args, **kwargs)
        self.start_urls = [url] if url else []
        self.extraction_rules = json.loads(extraction_rules) if extraction_rules else {}
        self.results = []

    def parse(self, response):
        item = {}
        # Try dynamic LLM rules first
        for field, selector in self.extraction_rules.items():
            value = response.css(selector).get()
            if value:
                item[field] = value.strip()
                
        # Fill in missing fields using hardcoded fallbacks
        for field, selectors in FALLBACK_SELECTORS.items():
            if not item.get(field):
                for sel in selectors:
                    val = response.css(sel).get()
                    if val:
                        item[field] = val.strip()
                        break
                        
        # Save raw body if nothing found, to allow LLM processing fallback
        if not item:
            item["_raw_html"] = response.text[:8000] # Limiting size
            
        self.results.append(item)
        yield item

@crochet.wait_for(timeout=15.0)
def _run_spider_crochet(url: str, extraction_rules: dict, results_list: list):
    """
    Run the Scrapy spider via crochet.
    """
    def crawler_results(signal, sender, item, response, spider):
        results_list.append(item)
        
    dispatcher.connect(crawler_results, signal=signals.item_scraped)
    
    settings = {
        'USER_AGENT': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'ROBOTSTXT_OBEY': False,
        'DOWNLOAD_TIMEOUT': 10,
        'LOG_LEVEL': 'WARNING',
        'AUTOTHROTTLE_ENABLED': True,
        # ── FIX: Explicitly disable the asyncio reactor in Scrapy settings ──
        # This prevents the "'EventLoop' object has no attribute '_reactor'" error.
        'TWISTED_REACTOR': 'twisted.internet.selectreactor.SelectReactor'
    }
    
    runner = CrawlerRunner(settings)
    deferred = runner.crawl(
        GenericSpider, 
        url=url, 
        extraction_rules=json.dumps(extraction_rules)
    )
    return deferred

async def run_ai_spider(url: str, selectors: dict = None) -> dict:
    """
    Async wrapper to run Scrapy inside the HybridEngine waterfall.
    """
    results = []
    try:
        # ── FIX: Call directly. @crochet.wait_for already makes it blocking-safe 
        # for a background thread, but we call it in the main loop thread? 
        # No, crochet.wait_for blocks the current thread until the deferred is done.
        # To avoid blocking the asyncio event loop, we use to_thread.
        await asyncio.to_thread(_run_spider_crochet, url, selectors or {}, results)
        
        if results:
            return results[0]
    except Exception as e:
        logger.error(f"[Scrapy Sniper] Error during execution: {e}")
        
    return {}

