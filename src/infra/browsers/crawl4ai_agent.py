"""
browser/crawl4ai_agent.py - Tier 6: Managed Async Scraper (Fixed)

Fixes applied:
1. RecursionError mitigation: increase sys.setrecursionlimit before crawl4ai calls
2. Added try-except wrapper for graceful escalation
"""

from __future__ import annotations
import asyncio
import sys
from typing import Optional, Any

from core import config
from core.logger import get_logger, alert

import os
os.environ["CRAWL4_AI_BASE_DIRECTORY"] = os.path.join(config.WORK_DIR, ".crawl4ai")

logger = get_logger(__name__)

from agents.base_agent import BaseBrowserAgent


class Crawl4AIAgent(BaseBrowserAgent):
    """
    Tier 6 scraper built on Crawl4AI. Fixed for Docker root + RecursionError.
    """

    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._crawler = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        self._last_content: str = ""

    async def _ensure_crawler_alive_locked(self) -> bool:
        """
        Check if Crawl4AI crawler is ready.
        CRITICAL FIX: No health scrape - Crawl4AI manages own browser lifecycle.
        """
        if self._crawler is not None:
            return True
        return await self._start_crawler()

    async def _start_crawler(self) -> bool:
        """Start Crawl4AI crawler with RecursionError mitigation."""
        try:
            from crawl4ai import BrowserConfig, AsyncWebCrawler
            
            # CRITICAL FIX: Increase recursion limit for Docker/Crawl4AI
            old_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(max(old_limit, 3000))
            
            logger.info("[Crawl4AI] Starting crawler...")
            
            browser_args = []
            if os.getuid() == 0:
                browser_args = ["--no-sandbox", "--disable-setuid-sandbox"]
            
            _proxy = {"server": self.current_proxy} if self.current_proxy else None
            browser_cfg = BrowserConfig(
                headless=True,
                extra_args=browser_args,
                proxy_config=_proxy
            )
            
            self._crawler = AsyncWebCrawler(config=browser_cfg)
            await self._crawler.__aenter__()
            alert("INFO", "Crawl4AI session started", {"proxy": self.current_proxy or "direct"})
            logger.info("[Crawl4AI] Ready.")
            return True
            
        except Exception as e:
            logger.error(f"[Crawl4AI] Failed to start: {e}")
            self._crawler = None
            return False
        finally:
            sys.setrecursionlimit(old_limit if 'old_limit' in dir() else 1000)

    async def close(self) -> None:
        async with self._lock:
            if self._crawler:
                try:
                    await self._crawler.__aexit__(None, None, None)
                except Exception:
                    pass
                finally:
                    self._crawler = None
            logger.info("[Crawl4AI] Closed.")

    async def is_alive(self) -> bool:
        async with self._lock:
            return self._crawler is not None

    async def scrape(self, url: str) -> Optional[str]:
        async with self._lock:
            if not await self._ensure_crawler_alive_locked():
                return None
            return await self._scrape_locked(url)

    async def _scrape_locked(self, url: str) -> Optional[str]:
        """Internal scrape with RecursionError handling."""
        if not self._crawler:
            return None

        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 3000))
        
        try:
            result = await self._crawler.arun(
                url=url,
                word_count_threshold=10,
                remove_overlay_elements=True,
                bypass_cache=True,
            )
            
            if result.success and result.markdown:
                content = result.markdown.strip()
                if content and not self.is_block_response(content):
                    self._last_content = content
                    return content
            return None
            
        except RecursionError as e:
            logger.error(f"[Crawl4AI] RecursionError - restarting crawler: {e}")
            await self._restart_crawler()
            raise  # Let HybridEngine escalate
        except Exception as e:
            logger.error(f"[Crawl4AI] Scrape error: {e}")
            return None
        finally:
            sys.setrecursionlimit(old_limit)

    async def _restart_crawler(self):
        """Restart crawler after RecursionError."""
        if self._crawler:
            try:
                await self._crawler.__aexit__(None, None, None)
            except Exception:
                pass
        self._crawler = None
        await asyncio.sleep(2)  # Cool-down before restart
        await self._start_crawler()

    # ── SEARCH METHODS (required by HybridEngine) ──

    async def submit_google_search(self, query: str) -> bool:
        """Not supported in Crawl4AI standalone."""
        return False

    async def extract_universal_data(self, use_browser: bool = False) -> dict:
        """Not supported in Crawl4AI standalone."""
        return {}

    async def search_google_ai_mode(
        self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None
    ) -> Optional[str]:
        """
        Use Crawl4AI to fetch content from an AI Mode URL.
        RecursionError-safe implementation.
        """
        if not ai_mode_url:
            return None
        
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 3000))
        
        try:
            async with self._lock:
                if not await self._ensure_crawler_alive_locked():
                    return None
                
                result = await self._crawler.arun(
                    url=ai_mode_url,
                    word_count_threshold=10,
                    remove_overlay_elements=True,
                    bypass_cache=True,
                )
                
                if result.success and result.markdown:
                    content = result.markdown.strip()
                    self._last_content = content
                    return content
                return None
                
        except RecursionError as e:
            logger.error(f"[Crawl4AI] RecursionError in search_google_ai_mode: {e}")
            await self._restart_crawler()
            raise
        except Exception as e:
            logger.error(f"[Crawl4AI] search_google_ai_mode error: {e}")
            return None
        finally:
            sys.setrecursionlimit(old_limit)

    async def get_page_source(self) -> str:
        """Return cached content from last scrape."""
        return self._last_content

    def is_block_response(self, content: str) -> bool:
        """Detect blocking/WAF responses."""
        if not content:
            return True
        block_patterns = [
            "access denied", "blocked", "forbidden", "captcha",
            "rate limit", "too many requests", "403 forbidden",
            "denied access", "unusual traffic"
        ]
        lower = content.lower()
        return sum(1 for p in block_patterns if p in lower) >= 3
