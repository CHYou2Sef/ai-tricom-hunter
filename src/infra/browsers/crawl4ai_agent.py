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
import re
import sys
from typing import Any, Optional

from core import config
from core.logger import alert, get_logger

os.environ["CRAWL4_AI_BASE_DIRECTORY"] = os.path.join(config.WORK_DIR, ".crawl4ai")

from agents.base_agent import BaseBrowserAgent  # noqa: E402

logger = get_logger(__name__)


class Crawl4AIAgent(BaseBrowserAgent):
    """
    Tier 6 scraper built on Crawl4AI.

    Golden-tier compliance:
      1) Crawl4AI fetch for JS-rendered content
      2) httpx fetch for fast HTML capture
      3) BeautifulSoup parsing for boilerplate reduction / clean extraction
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
        if not self._crawler:
            return None

        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old_limit, 3000))

        try:
            result = await self._crawler.arun(
                url=url,
                word_count_threshold=5,  # Lower threshold → faster return
                remove_overlay_elements=True,
                bypass_cache=True,
                cache_mode="bypass",
                page_timeout=20,
                delay_before_return_html=0.0,
            )

            crawl_md = None
            if result and getattr(result, "success", False) and getattr(result, "markdown", None):
                crawl_md = str(result.markdown or "").strip()

            merged = await self._golden_postprocess_url(url, crawl_md)
            if merged:
                self._last_content = merged
                return merged
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

        Golden-tier compliance:
          - Crawl4AI for rendered content
          - httpx+BeautifulSoup postprocessing for clean extraction

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

                if not self._crawler:
                    return None

                result = await self._crawler.arun(
                    url=ai_mode_url,
                    word_count_threshold=5,
                    remove_overlay_elements=True,
                    bypass_cache=True,
                    cache_mode="bypass",
                    page_timeout=20,
                    delay_before_return_html=0.0,
                )

                crawl_md = None
                if (
                    result
                    and getattr(result, "success", False)
                    and getattr(result, "markdown", None)
                ):
                    crawl_md = str(result.markdown or "").strip()

                merged = await self._golden_postprocess_url(ai_mode_url, crawl_md)
                if merged:
                    self._last_content = merged
                    return merged
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

    # ── Golden-tier helpers (Crawl4AI + httpx + BeautifulSoup) ──────────

    def _re_whitespace_collapse(self, text: str) -> str:
        return " ".join((text or "").split())

    async def _fetch_html_httpx(self, url: str, timeout_s: float = 15.0) -> str | None:
        """
        Fast HTML capture using httpx for the same URL.
        Used to complement Crawl4AI markdown with DOM parsing via BeautifulSoup.
        """
        try:
            import httpx
        except ImportError:
            return None

        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(timeout_s),
                follow_redirects=True,
                headers={
                    "User-Agent": getattr(self, "user_agent", None)
                    or "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/120 Safari/537.36",
                },
            ) as client:
                resp = await client.get(url)
                if resp.status_code >= 400:
                    return None
                html = resp.text or ""
                return html if html.strip() else None
        except Exception:
            return None

    def _html_to_text_bs4(self, html: str, max_chars: int = 120_000) -> str:
        """
        Convert HTML → text using BeautifulSoup, with lightweight cleanup.
        """
        try:
            from bs4 import BeautifulSoup
        except ImportError:
            return html

        soup = BeautifulSoup(html, "html.parser")

        for tag in soup(["script", "style", "noscript", "svg"]):
            tag.decompose()

        text = soup.get_text(separator=" ", strip=True)
        text = self._re_whitespace_collapse(text)

        if max_chars and len(text) > max_chars:
            text = text[:max_chars]
        return text

    def _merge_crawl4ai_and_bs4(self, crawl4ai_markdown: str, bs4_text: str | None) -> str:
        """
        Merge sources into a single text blob for downstream regex extraction.
        """
        crawl4ai_markdown = (crawl4ai_markdown or "").strip()
        bs4_text = (bs4_text or "").strip() if bs4_text else ""

        if bs4_text and crawl4ai_markdown:
            merged = f"{crawl4ai_markdown}\n\n--- HTTPX+BS4 EXTRACT ---\n{bs4_text}"
        elif bs4_text:
            merged = bs4_text
        else:
            merged = crawl4ai_markdown

        if len(merged) > 180_000:
            merged = merged[:180_000]
        return merged

    async def _golden_postprocess_url(self, url: str, crawl4ai_markdown: str | None) -> str | None:
        """
        After Crawl4AI, capture HTML via httpx + parse with BeautifulSoup,
        then return a merged cleaned representation.
        """
        bs_html = await self._fetch_html_httpx(url)
        bs_text = self._html_to_text_bs4(bs_html) if bs_html else None

        merged = self._merge_crawl4ai_and_bs4(
            crawl4ai_markdown or "",
            bs_text,
        )

        if merged and not self.is_block_response(merged):
            return merged
        return None

    # ── Content helpers ────────────────────────────────────────────────────

    async def get_page_source(self) -> str:
        """Return cached content from last scrape."""
        return self._last_content
