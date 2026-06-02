"""
browser/crawl4ai_agent.py - Tier 6: Managed Async Scraper

Fixes applied:
1. RecursionError mitigation: sys.setrecursionlimit raised before crawl4ai calls
2. `search_google_ai_mode` signature aligned with BaseBrowserAgent (**kwargs)
3. Null-guard added before `self._crawler.arun()` — Pyright NoneType dereference
4. Type annotations modernised: `Optional[X]` → `X | None` (PEP 604)
5. Import ordering corrected (isort)
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any

from core import config
from core.logger import alert, get_logger

os.environ["CRAWL4_AI_BASE_DIRECTORY"] = os.path.join(config.WORK_DIR, ".crawl4ai")

from agents.base_agent import BaseBrowserAgent  # noqa: E402

logger = get_logger(__name__)


class Crawl4AIAgent(BaseBrowserAgent):
    """
    Tier 6 scraper built on Crawl4AI.
    Fixed for Docker root + RecursionError + correct BaseBrowserAgent contract.
    """

    def __init__(self, worker_id: int = 0) -> None:
        super().__init__(worker_id)
        self._crawler = None
        self.current_proxy: str | None = None
        self._lock = asyncio.Lock()
        self._last_content: str = ""

    # ── Internal crawler lifecycle ─────────────────────────────────────────

    async def start(self) -> bool:
        """Start the crawler explicitly (HybridEngine lifecycle requirement)."""
        async with self._lock:
            return await self._ensure_crawler_alive_locked()

    async def _ensure_crawler_alive_locked(self) -> bool:
        """
        Check if Crawl4AI crawler is ready.
        CRITICAL FIX: No health scrape — Crawl4AI manages its own browser lifecycle.
        """
        if self._crawler is not None:
            return True
        return await self._start_crawler()

    async def _start_crawler(self) -> bool:
        """Start Crawl4AI crawler with RecursionError mitigation."""
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig

            # CRITICAL FIX: Increase recursion limit for Docker/Crawl4AI
            old_limit = sys.getrecursionlimit()
            sys.setrecursionlimit(max(old_limit, 3000))

            logger.info("[Crawl4AI] Starting crawler...")

            # ── HIGH-PERFORMANCE FLAGS (Golden-Tiers mode) ─────────────────
            # Minimize RAM/CPU: disable background processes, images, GPU.
            browser_args: list[str] = [
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-default-apps",
                "--disable-extensions",
                "--disable-sync",
                "--disable-translate",
                "--disable-features=TranslateUI",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                "--disable-background-timer-rendering",
                "--disable-compare-cursor",
                "--no-first-run",
                "--metrics-recording-only",
                "--mute-audio",
                "--blink-settings=imagesEnabled=false",
                "--disable-image-extension",
                "--hide-scrollbars",
                "--disable-logging",
                "--no-zygote",
            ]

            _proxy = {"server": self.current_proxy} if self.current_proxy else None
            browser_cfg = BrowserConfig(
                headless=True,
                extra_args=browser_args,
                proxy_config=_proxy,
                # ── Performance tunables ──────────────────────────────────────
                page_timeout=30,               # Max wait for page load (ms)
                browser_type="chromium",
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
            sys.setrecursionlimit(1000)

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

    # ── Scraping ───────────────────────────────────────────────────────────

    async def scrape(self, url: str) -> str | None:
        async with self._lock:
            if not await self._ensure_crawler_alive_locked():
                return None
            return await self._scrape_locked(url)

    async def _scrape_locked(self, url: str) -> str | None:
        """Internal scrape with RecursionError handling."""
        # FIX 3: explicit null-guard before calling arun — Pyright NoneType dereference
        if not self._crawler:
            return None

        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 3000))

        try:
            # ── HIGH-PERFORMANCE arun params (Golden-Tiers) ───────────────────
            result = await self._crawler.arun(
                url=url,
                word_count_threshold=5,         # Lower threshold → faster return
                remove_overlay_elements=True,
                bypass_cache=True,
                cache_mode="bypass",             # Always fresh fetch for contact pages
                page_timeout=20,                 # Max 20s per page
                delay_before_return_html=0.0,    # No delay — speed first
            )

            if result.success and result.markdown:
                content = result.markdown.strip()
                if content and not self.is_block_response(content):
                    self._last_content = content
                    return content
            return None

        except RecursionError as e:
            logger.error(f"[Crawl4AI] RecursionError — restarting crawler: {e}")
            await self._restart_crawler()
            raise  # Let HybridEngine escalate
        except Exception as e:
            logger.error(f"[Crawl4AI] Scrape error: {e}")
            return None
        finally:
            sys.setrecursionlimit(old_limit)

    async def _restart_crawler(self) -> None:
        """Restart crawler after RecursionError."""
        if self._crawler:
            try:
                await self._crawler.__aexit__(None, None, None)
            except Exception:
                pass
        self._crawler = None
        await asyncio.sleep(2)  # Cool-down before restart
        await self._start_crawler()

    # ── Search / AI-mode methods ───────────────────────────────────────────

    async def submit_google_search(self, query: str) -> bool:
        """Not supported in Crawl4AI standalone."""
        return False

    async def extract_universal_data(self, use_browser: bool = False) -> dict:  # type: ignore[override]
        """Not supported in Crawl4AI standalone."""
        return {}

    async def search_google_ai_mode(
        self,
        prompt: str,
        ai_mode_url: str | None = None,
        row: Any | None = None,
        **kwargs: Any,
    ) -> str | None:
        """Use Crawl4AI to fetch content from an AI Mode URL.

        FIX 2: signature now includes **kwargs to match BaseBrowserAgent contract.
        FIX 3: null-guard on self._crawler before arun() call.
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

                # FIX 3: explicit null-guard — Pyright cannot infer state after async call
                if not self._crawler:
                    return None

                # ── HIGH-PERFORMANCE arun params (Golden-Tiers) ───────────────────
                result = await self._crawler.arun(
                    url=ai_mode_url,
                    word_count_threshold=5,         # Lower threshold → faster return
                    remove_overlay_elements=True,
                    bypass_cache=True,
                    cache_mode="bypass",
                    page_timeout=20,                  # Max 20s per page
                    delay_before_return_html=0.0,     # Speed first
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

    # ── Content helpers ────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return cached content from last scrape."""
        return self._last_content

