"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/botasaurus_agent.py                                             ║
║                                                                          ║
║  Tier 2: Undefeatable Anti-Detect Agent                                  ║
║                                                                          ║
║  Uses Botasaurus for highest success rate against Cloudflare/CAPTCHAs.   ║
║  Features built-in caching, profile persistence, and stealth.            ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import os
import re
import asyncio
from typing import Optional

from core import config
from agents.base_agent import BaseBrowserAgent
from core.logger import get_logger, alert

logger = get_logger(__name__)

# Cache management flag based on config
# Note: In Botasaurus, caching is enabled via the decorator.
# However, to allow dynamic URLs, it's easier to use the driver directly or wrap.
# For simplicity, we will define standalone functions decorated with @browser
# but since the URLs change frequently and we are building a stateful agent,
# we can also just instantiate the Botasaurus Driver directly if we want more control.
# The Botas_plan says: "keep scraping tasks as standalone functions".

from botasaurus.browser import browser, Driver
from botasaurus.profile import Profile

# ── STANDALONE BOTASAURUS TASKS ──

@browser(
    headless=False,
    profile="botasaurus_default",
    block_images=True,
    cache=False  # We rely on our own AUDIT.json for persistence
)
def search_google_ai_task(driver: Driver, data: dict):
    query = data.get("query")
    from common.search_engine import generate_google_ai_url
    url = generate_google_ai_url(query)
    
    driver.get(url)
    driver.sleep(2)
    
    # Handle captchas here if any (Botasaurus should bypass most automatically)
    return driver.page_html

@browser(
    headless=False,
    profile="botasaurus_default",
    block_images=True,
    cache=False
)
def crawl_url_task(driver: Driver, data: dict):
    url = data.get("url")
    driver.get(url)
    driver.sleep(2)
    return driver.page_html

@browser(
    headless=False,
    profile="botasaurus_default",
    block_images=True,
    cache=False
)
def submit_google_search_task(driver: Driver, data: dict):
    query = data.get("query")
    import urllib.parse
    encoded = urllib.parse.quote_plus(query)
    url = f"https://www.google.com/search?q={encoded}"
    driver.get(url)
    driver.sleep(2)
    html = driver.page_html
    return bool(html and len(html) > 500)

@browser(
    headless=False,
    profile="botasaurus_default",
    block_images=True,
    cache=False
)
def search_gemini_ai_task(driver: Driver, data: dict):
    query = data.get("query")
    driver.get(config.GEMINI_URL)
    driver.sleep(2)
    
    # Needs actual interaction for Gemini, this is basic
    input_box = driver.select("textarea")
    if input_box:
        driver.type("textarea", query)
        driver.sleep(1)
        driver.click("button[type='submit']")
        driver.sleep(4)
    return driver.page_html


class BotasaurusAgent(BaseBrowserAgent):
    """
    Tier 2 stealth browser agent built on Botasaurus.
    """

    def __init__(self, worker_id: int = 0, proxy: Optional[str] = None):
        super().__init__(worker_id)
        self._proxy = proxy

    async def start(self) -> None:
        """Initialize any agent-level state."""
        logger.info(f"[Botasaurus] 🚀 Starting Botasaurus Agent for Worker {self.worker_id}")
        # Botasaurus handles driver lifecycle per task, but we can manage cache here if needed.
        if config.BOTASAURUS_CACHE:
            self._cleanup_cache()

    async def close(self) -> None:
        """Cleanup agent."""
        logger.info("[Botasaurus] Closed.")

    def _cleanup_cache(self):
        """Cleans up old cache files to save disk space."""
        # Botasaurus creates an 'output' folder for caches by default.
        import time
        from pathlib import Path
        output_dir = Path("output")
        if output_dir.exists():
            max_age = getattr(config, 'BOTASAURUS_CACHE_MAX_AGE_HOURS', 24) * 3600
            now = time.time()
            for f in output_dir.glob("*.json"):
                if now - f.stat().st_mtime > max_age:
                    try:
                        f.unlink()
                        logger.debug(f"[Botasaurus] Removed old cache file {f}")
                    except Exception as e:
                        pass

    async def rotate_proxy(self) -> None:
        # Proxies can be passed to the decorator, but since we use predefined decorators
        # we would need to dynamically construct them or pass proxy in data.
        logger.info(f"[Botasaurus-Worker-{self.worker_id}] Proxy rotation not natively dynamic via decorator yet.")

    async def goto_url(self, url: str) -> bool:
        # Standalone task
        html = await asyncio.to_thread(crawl_url_task, {"url": url})
        return bool(html)

    async def get_page_source(self) -> str:
        # Since Botasaurus spins up/down the browser per task with decorators, 
        # this pattern doesn't fit get_page_source perfectly. 
        return ""

    async def search_google_ai(self, query: str) -> Optional[str]:
        logger.info(f"[Botasaurus] 🔍 Google AI Mode: {query}")
        try:
            html = await asyncio.to_thread(search_google_ai_task, {"query": query})
            return html
        except Exception as e:
            logger.error(f"[Botasaurus] Error: {e}")
            return None

    async def search_google_ai_mode(self, query: str) -> Optional[str]:
        return await self.search_google_ai(query)

    async def submit_google_search(self, query: str) -> bool:
        logger.info(f"[Botasaurus] 🔍 Google Search: {query}")
        try:
            success = await asyncio.to_thread(submit_google_search_task, {"query": query})
            return success
        except Exception as e:
            logger.error(f"[Botasaurus] Error: {e}")
            return False

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        logger.info(f"[Botasaurus] 🤖 Gemini search: {query}")
        try:
            html = await asyncio.to_thread(search_gemini_ai_task, {"query": query})
            return html
        except Exception as e:
            logger.error(f"[Botasaurus] Error: {e}")
            return None

    async def crawl_url(self, url: str) -> str:
        logger.info(f"[Botasaurus] → {url}")
        try:
            html = await asyncio.to_thread(crawl_url_task, {"url": url})
            if not html:
                return ""
            text = re.sub(r"<[^>]+>", " ", html)
            text = re.sub(r"\s+", " ", text).strip()
            return text[:8000]
        except Exception as e:
            logger.error(f"[Botasaurus] Error: {e}")
            return ""

    async def crawl_website(self, url: str) -> str:
        return await self.crawl_url(url)

    async def generate_human_noise(self) -> None:
        pass # Not critical for Botasaurus due to its own anti-detect features
