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

from __future__ import annotations
import asyncio
import re
from typing import Optional, List, Any, Dict

from core import config
from core.logger import get_logger, alert

import os
# Fix: Prevent Crawl4AI from trying to create its database in the (read-only) home directory
os.environ["CRAWL4_AI_BASE_DIRECTORY"] = os.path.join(config.WORK_DIR, ".crawl4ai")

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

    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self._crawler = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        self._last_health_check = 0.0
        # Contract: get_page_source() must never return None.
        self._last_content: str = ""


    async def _ensure_crawler_alive_locked(self) -> bool:
        """Check if the Crawl4AI crawler is ready.

        Crawl4AI already manages its own browser lifecycle; repeatedly running
        an internal "health scrape" can trigger Playwright recursion storms
        (observed as `maximum recursion depth exceeded` during launch).

        Strategy:
          - If crawler exists, assume alive (no extra scrape).
          - If crawler missing, start it.
          - If start fails, return False so HybridEngine escalates tiers.
        """
        if self._crawler:
            return True

        await self._start_locked()
        return self._crawler is not None


    async def get_page_source(self) -> str:
        """Returns the last scraped markdown content for UUE parsing."""
        return getattr(self, "_last_content", "")

    # ─────────────────────────────────────────────────────────────────
    # LIFECYCLE
    # ─────────────────────────────────────────────────────────────────

    async def start(self) -> None:
        """Initialise the Crawl4AI crawler instance."""
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        """Internal lock-free start."""
        if self._crawler: return
        try:
            from crawl4ai import AsyncWebCrawler, BrowserConfig  # type: ignore
        except ImportError:
            raise RuntimeError("crawl4ai is not installed.")

        logger.info("[Crawl4AI] 🕷️ Initialising Tier 3 crawler...")
        
        if config.PROXY_ENABLED:
            if not self.current_proxy:
                from common.proxy_manager import get_next_proxy
                self.current_proxy = await get_next_proxy()
            else:
                logger.debug(f"[Crawl4AI] Re-using existing proxy: {self.current_proxy}")

        browser_args = ["--no-sandbox", "--disable-setuid-sandbox"] if os.getuid() == 0 else []
        _proxy = {"server": self.current_proxy} if self.current_proxy else None
        browser_cfg = BrowserConfig(
            headless=getattr(config, "HEADLESS", True),
            extra_args=browser_args,
            proxy_config=_proxy
        )
        self._crawler = AsyncWebCrawler(config=browser_cfg)
        await self._crawler.__aenter__()
        alert("INFO", "Crawl4AI session started", {"proxy": self.current_proxy or "direct"})
        logger.info("[Crawl4AI] ✅ Ready.")

    async def close(self) -> None:
        """Release Crawl4AI resources."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
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

    async def is_alive(self) -> bool:
        """Check if the agent is ready."""
        async with self._lock:
            return await self._ensure_crawler_alive_locked()

    async def scrape(self, url: str) -> Optional[str]:
        """Scrape a URL and return clean Markdown content."""
        async with self._lock:
            content = await self._scrape_locked(url)
            self._last_content = content or ""
            return content

    async def _scrape_locked(self, url: str) -> Optional[str]:
        """Internal lock-free scrape."""
        if not await self._ensure_crawler_alive_locked():
            return None

        speed_multiplier = getattr(config, "NETWORK_SPEED_MULTIPLIER", 1.0)
        backoff_delays = [d * speed_multiplier for d in [5, 15, 30]]

        for attempt, delay in enumerate(backoff_delays, start=1):
            try:
                logger.info(f"[Crawl4AI] Scraping (attempt {attempt}/3): {url}")
                if not self._crawler:
                    return None
                result = await self._crawler.arun(
                    url=url,
                    word_count_threshold=10,
                    exclude_external_links=True,
                    remove_overlay_elements=True,
                    bypass_cache=True,
                )


                if result.success and result.markdown:
                    content = result.markdown.strip() or ""
                    
                    # Post-navigation health check (detect immediate blocks)
                    if self.is_block_response(content):
                        await self.report_proxy_error(self.current_proxy, 403)
                        await self.rotate_proxy()
                        if attempt < len(backoff_delays):
                            await asyncio.sleep(delay)
                            continue
                        return None

                    logger.info(f"[Crawl4AI] ✅ Got {len(content)} chars from {url}")
                    return content

                if result.status_code in (429, 403, 402, 401) or self.is_block_response(result.markdown or ""):
                    alert("WARN", f"Crawl4AI rate-limited or blocked (HTTP {result.status_code})", {"url": url, "retry_in": f"{delay}s"})
                    
                    status_to_report = result.status_code if result.status_code in (429, 403, 402, 401) else 403
                    await self.report_proxy_error(self.current_proxy, status_to_report)
                    
                    await self.rotate_proxy()
                    await asyncio.sleep(delay)
                    continue

                logger.warning(f"[Crawl4AI] Empty or failed result for {url} (status={result.status_code})")
                return None

            except Exception as exc:
                logger.error(f"[Crawl4AI] Attempt {attempt} failed: {exc}")
                if self.is_block_response(exc):
                    await self.report_proxy_error(self.current_proxy, 403)
                    await self.rotate_proxy()
                
                if attempt < len(backoff_delays):
                    await asyncio.sleep(delay)
                    continue
                return None

        logger.error(f"[Crawl4AI] All attempts exhausted for {url}")
        return None

    async def crawl_website(self, base_url: str, max_pages: int = 3) -> str:
        """Deep-crawl a website: homepage + up to max_pages sub-pages."""
        async with self._lock:
            return await self._crawl_website_locked(base_url, max_pages)

    async def _crawl_website_locked(self, base_url: str, max_pages: int = 3) -> str:
        """Internal lock-free deep crawl."""
        all_content: List[str] = []

        # ── Scrape homepage ────────────────────────────────────────
        homepage = await self._scrape_locked(base_url)
        if homepage:
            all_content.append(f"## {base_url}\n\n{homepage}")

        # ── Discover and visit contact/about pages ─────────────────
        sub_urls = self._extract_contact_links(homepage or "", base_url)
        for url in sub_urls[:max_pages - 1]:
            sub_content = await self._scrape_locked(url)
            if sub_content:
                all_content.append(f"\n## {url}\n\n{sub_content}")
            await asyncio.sleep(1.5)  # Polite crawl delay

        content = "\n\n---\n\n".join(all_content)
        self._last_content = content
        return content

    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """
        Use Crawl4AI to scrape Google AI Mode results for a query.

        Google AI Mode (udm=50) is a dynamic SPA — the AI answer is streamed
        after the page loads. A plain scrape returns an empty shell.
        We use Crawl4AI's js_code hook to wait for the AI response container.
        """
        from common.search_engine import extract_search_terms, generate_google_ai_url
        search_query = extract_search_terms(prompt)
        
        if ai_mode_url:
            import urllib.parse
            url = ai_mode_url + urllib.parse.quote_plus(search_query)
        else:
            url = generate_google_ai_url(prompt)
        logger.info(f"[Crawl4AI] 🔍 Google AI Mode (JS-wait): {prompt[:80]}...")
        async with self._lock:
            return await self._search_google_ai_mode_locked(url)

    async def _search_google_ai_mode_locked(self, url: str) -> Optional[str]:
        """Internal: scrape Google AI Mode with JS wait for dynamic answer."""
        if not await self._ensure_crawler_alive_locked():
            return None

        # JS injected AFTER page load: waits up to 30s for the AI answer container.
        # Google AI Mode renders its answer inside [data-hveid], .YzFz, or .kno-result.
        wait_js = """
        (async () => {
            const selectors = [
                '[data-attrid="wa:/description"]',
                '.kno-rdesc',
                '.IZ6rdc',
                '[jsname="yEVEwb"]',
                '.wDYxhc',
                '.LGOjhe',
            ];
            for (let i = 0; i < 60; i++) {
                for (const sel of selectors) {
                    const el = document.querySelector(sel);
                    if (el && el.innerText && el.innerText.length > 50) return true;
                }
                await new Promise(r => setTimeout(r, 500));
            }
            return false;
        })()
        """
        # Crawl4AI/Playwright recursion storms appear during BrowserType.launch /
        # internal async trampoline when the crawler is repeatedly resurrected.
        # Hard cap this entrypoint per call so HybridEngine can escalate tiers.
        try:
            from crawl4ai import CrawlerRunConfig, CacheMode  # type: ignore
            run_cfg = CrawlerRunConfig(
                js_code=wait_js,
                wait_for="[data-attrid='wa:/description'],.kno-rdesc,.wDYxhc",
                wait_for_timeout=25000,
                word_count_threshold=10,
                remove_overlay_elements=True,
                cache_mode=CacheMode.BYPASS,
            )
            if not self._crawler:
                return None
            assert self._crawler is not None
            result = await self._crawler.arun(url=url, config=run_cfg)
        except Exception as exc:
            # If Crawl4AI is throwing recursion/async loop errors, do not try again
            # inside this tier; let HybridEngine escalate.
            exc_str = str(exc).lower()
            if "maximum recursion depth exceeded" in exc_str:
                raise

            if isinstance(exc, (ImportError, TypeError)):
                # CrawlerRunConfig not available — log version for diagnostics
                try:
                    import crawl4ai as _c4a  # type: ignore
                    _ver = getattr(_c4a, "__version__", "unknown")
                except Exception:
                    _ver = "not installed"
                logger.warning(
                    f"[Crawl4AI] CrawlerRunConfig not available (crawl4ai=={_ver}). "
                    f"Trying minimal arun() with JS wait..."
                )
                # Use the old-style arun() API that only takes a URL + kwargs
                # This still runs the full Playwright engine (not a bare HTTP scrape)
                if not self._crawler:
                    return None
                try:
                    result = await self._crawler.arun(
                        url=url,
                        wait_for="[data-attrid='wa:/description'],.kno-rdesc,.wDYxhc",
                        timeout=30000,
                        word_count_threshold=10,
                        remove_overlay_elements=True,
                        bypass_cache=True,
                    )
                    content = (
                        getattr(result, "markdown", None)
                        or getattr(result, "text", None)
                        or ""
                    ).strip()
                    if content and not self.is_block_response(content):
                        self._last_content = content
                        return content
                    logger.warning("[Crawl4AI] Minimal arun() also returned empty/blocked. Escalating.")
                    return None
                except Exception as inner_exc:
                    logger.error(f"[Crawl4AI] Minimal arun() failed: {inner_exc}")
                    return None
            raise


        if result and result.success and result.markdown:
            content = result.markdown.strip()
            if self.is_block_response(content):
                logger.warning("[Crawl4AI] Google AI Mode — blocked/CAPTCHA response detected.")
                await self.report_proxy_error(self.current_proxy, 403)
                return None
            logger.info(f"[Crawl4AI] ✅ Google AI Mode — {len(content)} chars extracted.")
            self._last_content = content
            return content

        logger.warning(f"[Crawl4AI] Google AI Mode returned empty (status={getattr(result, 'status_code', '?')}). Falling back to plain page.")
        # Last resort: return whatever was rendered
        fallback = getattr(result, "markdown", None) or getattr(result, "html", None) or ""
        self._last_content = fallback
        return fallback or None

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Alias for search_google_ai — maintains HybridEngine interface.

        Important: do not allow empty prompts to flow into DuckDuckGo/Google URLs
        (e.g. google.com/search?q=). When prompt is empty we fail fast so
        HybridEngine can escalate to another tier.
        """
        if prompt is None or not prompt.strip():
            raise ValueError("Crawl4AIAgent.search_google_ai_mode() received empty prompt; refusing to build AI-mode URL.")
        return await self.search_google_ai(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Interactive search fallback for Crawl4AI."""
        return await self.search_google_ai(prompt, ai_mode_url=ai_mode_url, row=row)

    async def submit_google_search(self, prompt: str) -> bool:
        """
        Crawl4AI implementation of submit_google_search.
        """
        import urllib.parse
        url = f"https://www.google.com/search?q={urllib.parse.quote_plus(prompt)}"
        logger.info(f"[Crawl4AI] 🔍 Google Search (submit): {prompt}")
        content = await self.scrape(url)
        # self._last_content is already updated in self.scrape()
        if content and len(content) > 200:
            logger.info(f"[Crawl4AI] ✅ submit_google_search — {len(content)} chars.")
            return True
        logger.warning("[Crawl4AI] submit_google_search — empty or blocked response.")
        return False

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy and restart the browser session."""
        async with self._lock:
            from common.proxy_manager import get_next_proxy
            new_proxy = await get_next_proxy()
            if new_proxy:
                logger.info(f"[Crawl4AI] ♻️  Rotating proxy to: {new_proxy}")
                self.current_proxy = new_proxy
                await self._close_locked()
                await self._start_locked()
            else:
                logger.warning("[Crawl4AI] No proxies available for rotation.")


    async def goto_url(self, url: str) -> bool:
        """
        Managed navigation for Tier 3. 
        Stores the result internally for use by get_page_source().
        """
        content = await self.scrape(url)
        # Note: self._last_content is already updated inside self.scrape()
        self._last_content = content or ""
        return bool(content)

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
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
