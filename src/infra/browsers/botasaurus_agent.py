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
from __future__ import annotations
import os
import re
import asyncio
from typing import Optional, Any, Dict, List

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


# ── STANDALONE BOTASAURUS TASKS ──

@browser(
    headless=True,
    block_images=True,
    cache=False,
    add_arguments=["--no-sandbox", "--disable-dev-shm-usage"],
    proxy=lambda data: data.get("proxy")
)
def search_google_ai_task(driver: Driver, data: dict):
    prompt = str(data.get("prompt") or "")
    ai_mode_url = data.get("ai_mode_url")

    from common.search_engine import generate_google_ai_url, extract_search_terms
    if ai_mode_url:
        import urllib.parse
        clean_query = extract_search_terms(prompt)
        url = ai_mode_url + urllib.parse.quote_plus(clean_query)
    else:
        url = generate_google_ai_url(prompt)
    
    driver.get(url)
    driver.sleep(2)
    
    # Handle captchas here if any (Botasaurus should bypass most automatically)
    return driver.page_html

@browser(
    headless=True,
    block_images=True,
    cache=False,
    add_arguments=["--no-sandbox", "--disable-dev-shm-usage"],
    proxy=lambda data: data.get("proxy")
)
def crawl_url_task(driver: Driver, data: dict):
    url = str(data.get("url") or "")
    driver.get(url)
    driver.sleep(2)
    return driver.page_html

@browser(
    headless=True,
    block_images=True,
    cache=False,
    add_arguments=["--no-sandbox", "--disable-dev-shm-usage"],
    proxy=lambda data: data.get("proxy")
)
def submit_google_search_task(driver: Driver, data: dict):
    prompt = str(data.get("prompt") or "")
    import urllib.parse
    encoded = urllib.parse.quote_plus(prompt)
    url = f"https://www.google.com/search?q={encoded}"
    driver.get(url)
    driver.sleep(2)
    html = driver.page_html
    return bool(html and len(html) > 500)

@browser(
    headless=True,
    block_images=True,
    cache=False,
    add_arguments=["--no-sandbox", "--disable-dev-shm-usage"],
    proxy=lambda data: data.get("proxy")
)
def search_gemini_ai_task(driver: Driver, data: dict):
    prompt = str(data.get("prompt") or "")
    driver.get(config.GEMINI_URL)
    driver.sleep(2)
    
    # Needs actual interaction for Gemini, this is basic
    input_box = driver.select("textarea")
    if input_box:
        driver.type("textarea", prompt)
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
        self.current_proxy = proxy
        self._lock = asyncio.Lock()
        self._last_content: str = ""


    async def start(self) -> None:
        """Initialize any agent-level state."""
        logger.info(f"[Botasaurus] 🚀 Starting Botasaurus Agent for Worker {self.worker_id}")
        
        if not self.current_proxy and config.PROXY_ENABLED:
            from common.proxy_manager import get_next_proxy
            self.current_proxy = await get_next_proxy()
            
        # Botasaurus handles driver lifecycle per task, but we can manage cache here if needed.
        if config.BOTASAURUS_CACHE:
            async with self._lock:
                await asyncio.to_thread(self._cleanup_cache)

    async def is_alive(self) -> bool:
        """Botasaurus is stateless/task-based, so it's always 'alive' if imports work."""
        return True

    async def close(self) -> None:
        """Cleanup agent."""
        logger.info("[Botasaurus] Closed.")

    def _cleanup_cache(self):
        """Cleans up old cache files to save disk space."""
        import time
        from pathlib import Path
        output_dir = Path("output")
        if output_dir.exists():
            max_age = getattr(config, 'BOTASAURUS_CACHE_MAX_AGE_HOURS', 24) * 3600
            now = time.time()
            for f in output_dir.glob("*.json"):
                try:
                    if now - f.stat().st_mtime > max_age:
                        f.unlink()
                        logger.debug(f"[Botasaurus] Removed old cache file {f}")
                except Exception:
                    pass

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy from the pool."""
        async with self._lock:
            from common.proxy_manager import get_next_proxy
            new_proxy = await get_next_proxy()
            if new_proxy:
                logger.info(f"[Botasaurus-Worker-{self.worker_id}] ♻️ Rotating proxy to: {new_proxy}")
                self.current_proxy = new_proxy
            else:
                logger.warning(f"[Botasaurus-Worker-{self.worker_id}] No proxies left for rotation.")

    async def goto_url(self, url: str) -> bool:
        # Standalone task
        async with self._lock:
            try:
                html = await asyncio.to_thread(crawl_url_task, {"url": url, "proxy": self.current_proxy})
                self._last_content = html or ""
                
                if self.is_block_response(self._last_content):
                    logger.warning(f"[Botasaurus] 🛡️ Block detected on {url}")
                    await self.report_proxy_error(url, 403)
                    await self.rotate_proxy()
                    return False
                    
                return bool(self._last_content)
            except Exception as e:
                if self.is_block_response(str(e)):
                    await self.report_proxy_error(url, 403)
                    await self.rotate_proxy()
                logger.error(f"[Botasaurus] goto_url error: {e}")
                return False

    async def get_page_source(self) -> str:
        # Botasaurus is task-based (decorator spins browser), so we store the
        # latest HTML content locally for BaseBrowserAgent parity.
        return self._last_content


    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        logger.info(f"[Botasaurus] 🔍 Google AI Mode: {prompt}")

        try:
            # On passe le profil dynamiquement via les data si nécessaire, 
            # ou on laisse Botasaurus gérer des profils temporaires isolés.
            async with self._lock:
                html = await asyncio.to_thread(search_google_ai_task, {
                    "prompt": prompt,
                    "ai_mode_url": ai_mode_url,
                    "profile": f"botasaurus_worker_{self.worker_id}",
                    "proxy": self.current_proxy
                })
                self._last_content = html or ""
                
                # Proactive Block Detection
                if self.is_block_response(self._last_content):
                    logger.warning(f"[Botasaurus] 🛡️ Block detected in page content.")
                    await self.report_proxy_error(ai_mode_url or "google_ai", 403)
                    await self.rotate_proxy()
                    return None
                    
                return self._last_content

        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(ai_mode_url or "google_ai", 403)
                await self.rotate_proxy()
            logger.error(f"[Botasaurus] Error: {e}")
            return None

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        return await self.search_google_ai(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Interactive search fallback for Botasaurus."""
        return await self.search_google_ai(prompt, ai_mode_url=ai_mode_url, row=row)


    async def submit_google_search(self, prompt: str) -> bool:
        logger.info(f"[Botasaurus] 🔍 Google Search: {prompt}")
        try:
            async with self._lock:
                success = await asyncio.to_thread(submit_google_search_task, {"prompt": prompt, "proxy": self.current_proxy})
                # Re-check content if possible (Botasaurus task returns bool here, but let's be safe)
                if not success:
                    await self.report_proxy_error("google_search", 403)
                    await self.rotate_proxy()
                return success
        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error("google_search", 403)
                await self.rotate_proxy()
            logger.error(f"[Botasaurus] Error: {e}")
            return False

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
        logger.info(f"[Botasaurus] 🤖 Gemini search: {prompt}")
        try:
            async with self._lock:
                html = await asyncio.to_thread(search_gemini_ai_task, {"prompt": prompt, "proxy": self.current_proxy})
                self._last_content = html or ""
                
                if self.is_block_response(self._last_content):
                    logger.warning(f"[Botasaurus] 🛡️ Block detected on Gemini")
                    await self.report_proxy_error("gemini", 403)
                    await self.rotate_proxy()
                    return None
                    
                return self._last_content

        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error("gemini", 403)
                await self.rotate_proxy()
            logger.error(f"[Botasaurus] Error: {e}")
            return None

    async def crawl_url(self, url: str) -> str:
        logger.info(f"[Botasaurus] → {url}")
        try:
            async with self._lock:
                html = await asyncio.to_thread(crawl_url_task, {"url": url, "proxy": self.current_proxy})
                self._last_content = html or ""
                if not self._last_content:
                    return ""
                    
                if self.is_block_response(self._last_content):
                    logger.warning(f"[Botasaurus] 🛡️ Block detected on {url}")
                    await self.report_proxy_error(url, 403)
                    await self.rotate_proxy()
                    return ""
                    
                # For crawl_url(), HybridEngine callers expect *text*, but keep
                # raw HTML available for get_page_source()/UUE.
                text = re.sub(r"<[^>]+>", " ", self._last_content)
                text = re.sub(r"\s+", " ", text).strip()
                return text[:8000]

        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(url, 403)
                await self.rotate_proxy()
            logger.error(f"[Botasaurus] Error: {e}")
            return ""

    async def crawl_website(self, url: str) -> str:
        return await self.crawl_url(url)

    async def generate_human_noise(self) -> None:
        pass # Not critical for Botasaurus due to its own anti-detect features
