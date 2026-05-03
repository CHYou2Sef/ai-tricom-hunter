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

GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"]'

class CloakAgent(BaseBrowserAgent):
    def __init__(self, worker_id: int = 0):
        super().__init__(worker_id)
        self.context = None
        self.page = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        self.profile_path = config.get_worker_profile_path(worker_id, "cloakbrowser")

    async def start(self) -> None:
        if not CLOAK_AVAILABLE:
            raise ImportError("cloakbrowser package is not installed. Run 'pip install cloakbrowser'")

        logger.info("[CloakBrowser] Starting Supreme Stealth Browser...")
        
        proxy_settings = None
        if config.PROXY_ENABLED and self.current_proxy:
            proxy_settings = self.current_proxy

        # Detect the stealth binary
        from core.config import find_cloak_binary
        exec_path = find_cloak_binary() or None

        # Cloak handles fingerprints at C++ level.
        # We use launch_persistent_context_async for session persistence.
        self.context = await launch_persistent_context_async(
            user_data_dir=self.profile_path,
            executable_path=exec_path,
            headless=getattr(config, "HEADLESS", False),
            proxy=proxy_settings,
            humanize=True, # Enable human-like behavior
            geoip=True,    # Auto-detect timezone/locale from proxy
        )
        
        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        
        alert("INFO", "CloakBrowser session started", {
            "worker": self.worker_id,
            "stealth": "Source-level C++ patches",
            "humanize": True
        })

    async def close(self) -> None:
        try:
            if self.context: await self.context.close()
        except Exception:
            pass
        finally:
            self.context = self.page = None

    async def get_page_source(self) -> str:
        return await self.page.content() if self.page else ""

    async def goto_url(self, url: str) -> bool:
        if not self.page: return False
        async with self._lock:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
                return True
            except Exception as e:
                logger.debug(f"[Cloak] Failed to visit {url}: {e}")
                return False

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """
        Supreme stealth search via Google AI Mode.
        """
        if not self.page: return None
        async with self._lock:
            try:
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
                
                url = generate_google_ai_url(search_query)
                logger.info(f"🕵️ [Cloak] Navigating to: {url}")
                
                await self.page.goto(url, wait_until="load", timeout=45000)
                await asyncio.sleep(2)
                
                await self._handle_google_cookies()
                
                # Wait for AI response to stream
                logger.info("⏳ [Cloak] Waiting for AI response to stream...")
                response_text = await self._wait_for_ai_response(timeout_sec=25)
                
                return response_text
            except Exception as e:
                logger.error(f"[Cloak] Search error: {e}")
                return None

    async def _wait_for_ai_response(self, timeout_sec: int = 25) -> Optional[str]:
        """Waits for Google AI Mode to finish streaming."""
        ai_selectors = ["code", "div[jsname='yEVEwb']", "div.mod"]
        deadline = asyncio.get_event_loop().time() + timeout_sec
        prev_text = ""
        
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.5)
            for selector in ai_selectors:
                try:
                    elements = await self.page.locator(selector).all()
                    texts = [await el.inner_text() for el in elements if await el.is_visible()]
                    if texts:
                        combined = "\n".join(texts)
                        if combined == prev_text and len(combined) > 50:
                            return combined
                        prev_text = combined
                except: continue
        return prev_text if prev_text else None

    async def submit_google_search(self, query: str) -> bool:
        if not self.page: return False
        async with self._lock:
            try:
                await self.page.goto(config.GOOGLE_URL, wait_until="load")
                await self._handle_google_cookies()
                
                search_box = self.page.locator(GOOGLE_SEARCH_INPUT).first
                if await search_box.is_visible():
                    await search_box.click()
                    await self.page.keyboard.type(query, delay=random.randint(50, 150))
                    await search_box.press("Enter")
                    return True
                return False
            except Exception as e:
                logger.error(f"[Cloak] Google Search Submission Error: {e}")
                return False

    async def _handle_google_cookies(self) -> None:
        try:
            selectors = ["button:has-text('Accept all')", "button:has-text('Accepter tout')", "#L2AGLb"]
            for s in selectors:
                btn = self.page.locator(s)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    await asyncio.sleep(1)
                    break
        except: pass

    async def crawl_website(self, url: str) -> str:
        """Deep crawl using Cloak's humanize behavior."""
        if not self.page: return ""
        async with self._lock:
            try:
                logger.info(f"🕸️ [Cloak] DeepCrawl: {url}")
                await self.page.goto(url, wait_until="domcontentloaded", timeout=20000)
                await asyncio.sleep(2)
                
                body_text = await self.page.inner_text("body")
                return f"--- PAGE: {url} ---\n{body_text}"
            except Exception as e:
                logger.error(f"[Cloak] Crawl error for {url}: {e}")
                return ""

    async def search_google_ai(self, query: str) -> Optional[str]:
        """Legacy AI search fallback."""
        return await self.search_google_ai_mode(query)

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        """Search via Gemini UI using Cloak stealth."""
        if not self.page: return None
        async with self._lock:
            try:
                await self.page.goto(config.GEMINI_URL, wait_until="load")
                await asyncio.sleep(4)
                # ... implementation similar to Patchright but with Cloak ...
                return "Gemini search not fully implemented for Cloak yet"
            except: return None
