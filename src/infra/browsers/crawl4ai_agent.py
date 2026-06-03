"""
browser/crawl4ai_agent.py - Tier 6: Managed Async Scraper

Fixes applied:
1. RecursionError mitigation: sys.setrecursionlimit raised before crawl4ai calls
2. `search_google_ai_mode` signature aligned with BaseBrowserAgent (**kwargs)
3. Null-guard added before `self._crawler.arun()` — Pyright NoneType dereference
4. Type annotations modernised: `Optional[X]` → `X | None` (PEP 604)
5. Import ordering corrected (isort)
6. JSON enforcement: search_google_ai_mode now validates and returns ONLY JSON blobs.
   Non-JSON raw text is dropped (returns None) so HybridEngine escalates correctly.
7. Improved stub comments: submit_google_search / extract_universal_data return
   False/{} deliberately so HybridEngine escalates to interactive tiers (2/5).
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any, Optional

from common.json_parser import parse_ai_mode_json
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
        """Start Crawl4AI crawler with RecursionError mitigation and version-safe BrowserConfig."""
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig
            import inspect

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

            # Build BrowserConfig using only params that exist in THIS version.
            # This prevents "unexpected keyword argument" errors when the installed
            # crawl4ai version differs from what the code was written against.
            sig = inspect.signature(BrowserConfig.__init__)
            accepted = set(sig.parameters.keys())

            kwargs: dict[str, Any] = {
                "headless": True,
                "extra_args": browser_args,
                "browser_type": "chromium",
            }

            # proxy: accepted in all recent versions (plain string or None)
            if "proxy" in accepted and self.current_proxy:
                kwargs["proxy"] = self.current_proxy

            # text_mode / light_mode / memory_saving_mode: reduce RAM
            for opt in (
                "text_mode",
                "light_mode",
                "memory_saving_mode",
                "max_pages_before_recycle",
            ):
                if opt in accepted:
                    kwargs[opt] = True if opt != "max_pages_before_recycle" else 5

            # viewport dict
            if "viewport" in accepted:
                kwargs["viewport"] = {"width": 1280, "height": 800}

            # No page_timeout — that was an old API that doesn't exist in current versions

            browser_cfg = BrowserConfig(**kwargs)

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
                word_count_threshold=3,  # Lower threshold → faster return
                remove_overlay_elements=True,
                bypass_cache=True,
                cache_mode="bypass",
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
        """Intentionally not implemented for Crawl4AI standalone.

        Crawl4AI has no interactive browser control (no page.type() / page.click()).
        Returning False signals HybridEngine to escalate this task to an interactive
        tier (Tier 2 SeleniumBase or Tier 5 Nodriver) that can actually type a query
        into Google and submit the form.
        """
        logger.debug("[Crawl4AI] submit_google_search: not supported — escalating to interactive tier.")
        return False

    async def extract_universal_data(self, use_browser: bool = False) -> dict:  # type: ignore[override]
        """Intentionally not implemented for Crawl4AI standalone.

        Extracting structured DOM data requires a live browser session with JS
        execution (Playwright/Selenium). Crawl4AI fetches static markdown via its
        own managed browser; it cannot expose a generic DOM extraction API.
        Returning {} signals HybridEngine to escalate to a tier that supports it.
        """
        logger.debug("[Crawl4AI] extract_universal_data: not supported — escalating to interactive tier.")
        return {}

    async def search_google_ai_mode(
        self,
        prompt: str,
        ai_mode_url: str | None = None,
        row: Any | None = None,
        **kwargs: Any,
    ) -> str | None:
        """Fetch an AI-Mode Google URL with Crawl4AI and return a JSON-only string.

        Architecture note:
          - This tier (6) is a *content fetcher*, NOT a search conductor.
          - The `prompt` parameter is logged for traceability but the actual
            search is already encoded in `ai_mode_url` by the primary tier (2/5).
          - Output is strictly validated: only a valid JSON blob is returned.
            If the fetched content contains no parseable JSON, None is returned
            so HybridEngine escalates to the next tier.

        Fixes:
          - **kwargs contract alignment with BaseBrowserAgent.
          - Null-guard on self._crawler before arun().
          - RecursionError-safe implementation.
          - FIX 6: JSON enforcement — parse_ai_mode_json filters non-JSON noise.
        """
        if not ai_mode_url:
            logger.debug("[Crawl4AI] search_google_ai_mode: no ai_mode_url provided — skipping.")
            return None

        logger.debug(
            f"[Crawl4AI] search_google_ai_mode called | url={ai_mode_url[:80]}... "
            f"| prompt_len={len(prompt) if prompt else 0}"
        )

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
                if not merged:
                    logger.debug("[Crawl4AI] search_google_ai_mode: empty merged content.")
                    return None

                # ── FIX 6: JSON-ONLY ENFORCEMENT ─────────────────────────────
                # Crawl4AI returns raw markdown/HTML text. The caller (phone_hunter)
                # expects either a JSON string or None. We run parse_ai_mode_json
                # to validate and extract the JSON blob, then re-serialize it as
                # a canonical JSON string for downstream consumers.
                parsed = parse_ai_mode_json(merged)
                if parsed is None:
                    logger.warning(
                        "[Crawl4AI] search_google_ai_mode: content fetched but contains NO "
                        "parseable JSON — returning None to trigger tier escalation. "
                        f"(url={ai_mode_url[:60]}..., content_len={len(merged)})"
                    )
                    return None

                json_str = json.dumps(parsed, ensure_ascii=False)
                self._last_content = json_str
                logger.info(
                    f"[Crawl4AI] ✅ search_google_ai_mode: JSON extracted "
                    f"(keys={list(parsed.keys())[:5]}, url={ai_mode_url[:60]}...)"
                )
                return json_str

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
