"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/cloak_agent.py                                                  ║
║                                                                          ║
║  CloakBrowser agent. (Supreme Stealth Tier)                              ║
║                                                                          ║
║  Leverages C++ source-level patched Chromium for maximum stealth.         ║
║  Drop-in replacement for Playwright but with source-level fingerprints.   ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
from __future__ import annotations
import os
import asyncio
import random
import re
import json
from typing import Optional, List, Dict, Any

try:
    from cloakbrowser import launch_persistent_context_async
    CLOAK_AVAILABLE = True
except ImportError:
    CLOAK_AVAILABLE = False

from core import config
from agents.base_agent import BaseBrowserAgent
from common.anti_bot import (
    is_captcha_page,
    get_fingerprint_bundle,
    action_delay_async,
)
from core.logger import get_logger, alert

logger = get_logger(__name__)

# ── Google Knowledge Panel / Instant Answer selectors ──────────────────────
GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"], textarea[title="Search"], input[title="Search"], textarea[title="Rechercher"], input[title="Rechercher"], [aria-label="Search"]'

# ── Gemini selectors ──────────────────────────────────────────────────────
GEMINI_INPUT_SELECTORS   = ["div[role='combobox']", ".ql-editor", "textarea"]
GEMINI_RESPONSE_SELECTORS = [
    ".model-response-text",
    "message-content",
    "div.message-content",
    ".response-container-content",
]

class CloakAgent(BaseBrowserAgent):
    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self.context = None
        self.page = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        self.profile_path = config.get_worker_profile_path(worker_id, "cloakbrowser")
        self._last_health_check = 0.0

    async def is_alive(self) -> bool:
        """Public health check with lock protection."""
        async with self._lock:
            if not self.page: return False
            try:
                await self.page.evaluate("1+1")
                return True
            except Exception:
                return False

    async def _ensure_page_locked(self) -> bool:
        """
        Defensive check: ensures self.page is not None AND the browser
        context is still responsive.
        """
        now = asyncio.get_event_loop().time()
        if self.page and (now - self._last_health_check < 5.0):
            return True

        if not self.page:
            await self._start_locked()
            if not self.page: return False

        try:
            # Heartbeat check
            await self.page.evaluate("1+1")
            self._last_health_check = now
            return True
        except Exception as e:
            logger.warning(f"[CloakBrowser] 💔 Page unresponsive: {e}. Resurrecting...")
            await self._close_locked()
            await self._start_locked()
            return self.page is not None

    async def start(self) -> None:
        """Launch CloakBrowser with supreme stealth config."""
        async with self._lock:
            await self._start_locked()

    async def _start_locked(self) -> None:
        """Internal lock-free start."""
        if self.page:
            return

        if not CLOAK_AVAILABLE:
            raise ImportError("cloakbrowser package is not installed. Run 'pip install cloakbrowser'")

        if not self.current_proxy and config.PROXY_ENABLED:
            from common.proxy_manager import get_next_proxy
            self.current_proxy = await get_next_proxy()

        logger.info(f"[CloakBrowser] Starting Supreme Stealth Browser (proxy={self.current_proxy or 'direct'})...")
        
        proxy_settings = None
        if config.PROXY_ENABLED and self.current_proxy:
            proxy_settings = self.current_proxy

        # Detect the stealth binary
        from core.config import find_cloak_binary
        exec_path = find_cloak_binary() or None

        try:
            # Cloak handles fingerprints at C++ level.
            # We use launch_persistent_context_async for session persistence.
            self.context = await launch_persistent_context_async(
                user_data_dir=self.profile_path,
                headless=getattr(config, "HEADLESS", False),
                proxy=proxy_settings,
                humanize=True, # Enable human-like behavior
                geoip=False,   # Temporarily disable geoip to avoid geoip2 missing dependency error just in case
                args=["--no-sandbox", "--disable-setuid-sandbox"] if os.getuid() == 0 else []
            )
            
            if not self.context:
                raise RuntimeError("Failed to create Cloak context")
                
            self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
            
            alert("INFO", "CloakBrowser session started", {
                "worker": self.worker_id,
                "stealth": "Source-level C++ patches",
                "humanize": True
            })
        except Exception as e:
            logger.error(f"[CloakBrowser] Startup failed: {e}")
            self.context = self.page = None
            raise

    async def close(self) -> None:
        """Gracefully close CloakBrowser."""
        async with self._lock:
            await self._close_locked()

    async def _close_locked(self) -> None:
        """Internal lock-free close."""
        try:
            if self.context:
                await self.context.close()
        except Exception:
            pass
        finally:
            self.context = self.page = None
            logger.info("[CloakBrowser] Browser closed.")

    async def get_page_source(self) -> str:
        """Return raw HTML of current page."""
        async with self._lock:
            return await self._get_page_source_locked()

    async def _get_page_source_locked(self) -> str:
        if not self.page:
            return ""
        try:
            return await self.page.content()
        except Exception:
            return ""

    async def goto_url(self, url: str) -> bool:
        """Navigate to URL."""
        async with self._lock:
            # Root-cause guard: self.page can be None after rotation/crash.
            if not await self._ensure_page_locked():
                return False
            return await self._goto_url_locked(url)


    async def _goto_url_locked(self, url: str) -> bool:
        """Internal lock-free navigation."""
        if not await self._ensure_page_locked():
            return False
        
        try:
            if not self.page:
                return False
            await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            
            # Post-navigation health check (detect immediate blocks)
            page_content = await self.page.content()
            if self.is_block_response(page_content):
                logger.warning(f"[Cloak] 🛡️ Block detected on {url}")
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return False
                
            return True
        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
            logger.debug(f"[Cloak] Failed to visit {url}: {e}")
            return False

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """⭐ PRIMARY SEARCH — Google AI Mode via CloakBrowser."""
        async with self._lock:
            return await self._search_google_ai_mode_locked(prompt, ai_mode_url, row)

    async def _search_google_ai_mode_locked(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        if not await self._ensure_page_locked():
            return None

        try:
            # Guard: never build/search with an empty prompt (prevents generating URLs with `q=` empty).
            prompt = (prompt or "").strip()
            if not prompt:
                raise ValueError("Empty prompt passed to Cloak search_google_ai_mode")

            from common.search_engine import generate_google_ai_url
            
            
            # Extract essential search terms
            search_query = prompt
            if len(prompt) > 200 or "###" in prompt:
                name_match = re.search(r"NAME:\s*(.*)", prompt)
                addr_match = re.search(r"ADDRESS:\s*(.*)", prompt)
                if name_match:
                    search_query = name_match.group(1).strip()
                    if addr_match:
                        search_query += f" {addr_match.group(1).strip()}"
            
            url = ai_mode_url or generate_google_ai_url(search_query)
            logger.info(f"🕵️ [Cloak] Navigating to: {url}")

            # Hard guard: prevent accidental navigation with empty q= parameter.
            if "q=" in url and re.search(r"[?&]q=(&|$)", url):
                raise ValueError(f"Refusing Cloak navigation with empty q parameter. url={url}")

            if not await self._ensure_page_locked(): return None
            if not self.page:
                return None
            await self.page.goto(url, wait_until="load", timeout=45000)
            await asyncio.sleep(2)
            
            # Post-navigation health check (detect immediate blocks)
            page_content = await self.page.content()
            if self.is_block_response(page_content):
                logger.warning(f"[Cloak] 🛡️ Block detected in AI Mode content.")
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return None
            
            if not self.page:
                return None
            await self._handle_google_cookies_locked()

            
            # Wait for AI response to stream
            logger.info("⏳ [Cloak] Waiting for AI response to stream...")
            return await self._wait_for_ai_response_locked(timeout_sec=25)
            
        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
            logger.error(f"[Cloak] Search error: {e}")
            return None

    async def _wait_for_ai_response_locked(self, timeout_sec: int = 25) -> Optional[str]:
        """Waits for Google AI Mode to finish streaming. Internal locked."""
        if not self.page:
            return None
        
        ai_selectors = ["code", "div[jsname='yEVEwb']", "div.mod"]
        deadline = asyncio.get_event_loop().time() + timeout_sec
        prev_text = ""
        
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.5)
            
            # Re-check page liveness in case of concurrent rotation or crash
            if not self.page:
                return prev_text if prev_text else None
            
            try:
                current_texts = []
                for selector in ai_selectors:
                    if not self.page: break
                    # Double guard before locator
                    try:
                        locator = self.page.locator(selector)
                        if await locator.count() > 0:
                            elements = await locator.all()
                            for el in elements:
                                if not self.page: break
                                if await el.is_visible():
                                    txt = await el.inner_text()
                                    if txt:
                                        current_texts.append(txt)
                    except: continue
                
                if current_texts:
                    combined = "\n".join(current_texts)
                    if combined == prev_text and len(combined) > 50:
                        return combined
                    prev_text = combined
                    
                    # Final check for block in streamed content
                    if self.is_block_response(combined):
                        logger.warning(f"[Cloak] 🛡️ Block detected in streaming content.")
                        await self.report_proxy_error(self.current_proxy, 403)
                        await self.rotate_proxy()
                        return None

            except Exception as e:
                logger.debug(f"[Cloak] AI Stream wait iteration failed: {e}")
                continue
        return prev_text if prev_text else None

    async def submit_google_search(self, prompt: str) -> bool:
        """Submit a standard Google search."""
        async with self._lock:
            return await self._submit_google_search_locked(prompt)

    async def _submit_google_search_locked(self, prompt: str) -> bool:
        """Internal lock-free search submission."""
        if not await self._ensure_page_locked():
            return False
        
        try:
            if not self.page:
                return False
            await self.page.goto(config.GOOGLE_URL, wait_until="load")
            
            # Detect immediate block
            page_content = await self.page.content()
            if self.is_block_response(page_content):
                logger.warning(f"[Cloak] 🛡️ Block detected on Google Search page.")
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return False

            await self._handle_google_cookies_locked()

            
            if not self.page: 
                return False
                
            try:
                search_box_locator = self.page.locator(GOOGLE_SEARCH_INPUT)
                if await search_box_locator.count() > 0:
                    search_box = search_box_locator.first
                    if await search_box.is_visible():
                        await search_box.click()
                        await self.page.keyboard.type(prompt, delay=random.randint(50, 150))
                        await search_box.press("Enter")
                        
                        # Post-submission check
                        await asyncio.sleep(2)
                        new_content = await self.page.content()
                        if self.is_block_response(new_content):
                            await self.report_proxy_error(self.current_proxy, 403)
                            await self.rotate_proxy()
                            return False
                            
                        return True
            except: pass
            return False
        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
            logger.error(f"[Cloak] Google Search Submission Error: {e}")
            return False

    async def _handle_google_cookies_locked(self) -> None:
        """Dismiss Google cookies. Internal locked."""
        if not self.page: return
        try:
            selectors = ["button:has-text('Accept all')", "button:has-text('Accepter tout')", "#L2AGLb"]
            for s in selectors:
                if not self.page: break
                try:
                    btn_locator = self.page.locator(s)
                    if await btn_locator.count() > 0 and await btn_locator.is_visible():
                        await btn_locator.click()
                        await asyncio.sleep(1)
                        break
                except: continue
        except Exception:
            pass

    async def crawl_website(self, url: str) -> str:
        """Deep crawl of a website."""
        async with self._lock:
            return await self._crawl_website_locked(url)

    async def _crawl_website_locked(self, url: str) -> str:
        """Internal lock-free crawl."""
        if not await self._ensure_page_locked():
            return ""
        
        try:
            logger.info(f"🕸️ [Cloak] DeepCrawl: {url}")
            if not self.page:
                return ""
            await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(2)
            
            if not self.page:
                return ""

            page_content = await self.page.content()
            if self.is_block_response(page_content):
                logger.warning(f"[Cloak] 🛡️ Block detected on {url}")
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return ""

            body_text = await self.page.inner_text("body")
            return f"--- PAGE: {url} ---\n{body_text}"
        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
            logger.error(f"[Cloak] Crawl error for {url}: {e}")
            return ""

    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Legacy AI search fallback."""
        return await self.search_google_ai_mode(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """Interactive search fallback for Cloak."""
        return await self.search_google_ai_mode(prompt, ai_mode_url=ai_mode_url, row=row)

    async def search_gemini_ai(self, prompt: str) -> Optional[str]:
        """Search via Gemini UI."""
        async with self._lock:
            return await self._search_gemini_ai_locked(prompt)

    async def _search_gemini_ai_locked(self, prompt: str) -> Optional[str]:
        if not await self._ensure_page_locked():
            return None

        try:
            logger.info(f"🚀 [Cloak-Gemini] DeepSearch: {prompt}")
            if not self.page:
                return None
            await self.page.goto(config.GEMINI_URL, wait_until="load")
            await asyncio.sleep(4)

            if not self.page:
                return None

            # Block detection on Gemini start page
            page_content = await self.page.content()
            if self.is_block_response(page_content):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
                return None

            chat_input = None
            for s in GEMINI_INPUT_SELECTORS:
                chat_input = await self._find_input_locked(s, timeout_ms=5000)
                if chat_input:
                    break

            if not chat_input:
                logger.warning("[Cloak-Gemini] Could not find input area.")
                return None

            if not self.page: return None
            await chat_input.click()
            await self._human_type_cloak_locked(prompt)
            await self.page.keyboard.press("Enter")

            return await self._wait_for_streaming_response_locked(GEMINI_RESPONSE_SELECTORS, stable_wait_sec=4)
        except Exception as e:
            if self.is_block_response(str(e)):
                await self.report_proxy_error(self.current_proxy, 403)
                await self.rotate_proxy()
            logger.error(f"[Cloak-Gemini] Error: {e}")
            return None

    async def _find_input_locked(self, selector: str, timeout_ms: int = 10000):
        if not self.page: return None
        try:
            await self.page.wait_for_selector(selector, timeout=timeout_ms)
            if not self.page: return None
            loc = self.page.locator(selector)
            if await loc.count() > 0:
                return loc.first
            return None
        except Exception:
            return None

    async def _human_type_cloak_locked(self, text: str) -> None:
        if not self.page: return
        for char in text:
            if not self.page: return
            await self.page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.04, 0.12))

    async def _extract_first_available_locked(self, selectors: list, timeout_ms: int = 3000) -> Optional[str]:
        """Try each selector; return the first non-empty text found. Internal locked."""
        if not self.page: return None
        for s in selectors:
            try:
                if not self.page: break
                await self.page.wait_for_selector(s, timeout=timeout_ms, state="visible")
                if not self.page: break
                loc = self.page.locator(s)
                if await loc.count() > 0:
                    text = await loc.first.text_content()
                    if text and text.strip():
                        return text.strip()
            except Exception:
                continue
        return None

    async def _wait_for_streaming_response_locked(self, selectors: list, stable_wait_sec: int = 4) -> Optional[str]:
        """Wait for streamed response to stabilize. Internal locked."""
        start = asyncio.get_event_loop().time()
        last_text = ""
        stable_count = 0
        while asyncio.get_event_loop().time() - start < 60:
            if not self.page: return last_text or None
            current = await self._extract_first_available_locked(selectors, timeout_ms=3000) or ""
            if current and current == last_text:
                stable_count += 1
                if stable_count >= stable_wait_sec:
                    return current
            else:
                stable_count = 0
                last_text = current
            await asyncio.sleep(1)
        return last_text or None

    async def rotate_proxy(self) -> None:
        """Rotate proxy and restart session."""
        async with self._lock:
            from common.proxy_manager import get_next_proxy
            new_proxy = await get_next_proxy()
            if new_proxy:
                logger.info(f"[Cloak] ♻️ Rotating proxy to: {new_proxy}")
                await self._close_locked()
                self.current_proxy = new_proxy
                await self._start_locked()
            else:
                logger.warning("[Cloak] No proxies left for rotation.")

    async def generate_human_noise(self) -> None:
        """Simulate human browsing in CloakBrowser."""
        async with self._lock:
            await self._generate_human_noise_locked()

    async def _generate_human_noise_locked(self) -> None:
        """Internal lock-free noise simulation."""
        if not self.context:
            return
            
        site = random.choice(config.HUMAN_NOISE_SITES)
        logger.info(f"🎭 [Human Noise] Simulating activity on: {site}")
        
        try:
            if not self.context: return
            noise_page = await self.context.new_page()
            if not noise_page: return
            
            await noise_page.goto(site, wait_until="domcontentloaded", timeout=20000)
            await asyncio.sleep(random.uniform(5, 12))
            
            for _ in range(random.randint(2, 5)):
                if not self.context or not noise_page: break
                # Mouse move / scroll
                await noise_page.mouse.move(random.randint(0, 800), random.randint(0, 600))
                await noise_page.evaluate(f"window.scrollBy(0, {random.randint(300, 800)})")
                await asyncio.sleep(random.uniform(1, 3))
            
            if noise_page:
                await noise_page.close()
            logger.info("🎭 [Human Noise] Simulation complete.")
        except Exception as exc:
            logger.debug(f"[Human Noise] Simulation error: {exc}")
