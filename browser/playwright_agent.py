"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/playwright_agent.py                                             ║
║                                                                          ║
║  Playwright browser agent. (ASYNC VERSION)                               ║
║                                                                          ║
║  Search strategy (no AI/LLM modes):                                     ║
║    1. Google search with raw identifiers (name + address + SIREN)        ║
║    2. Scan the FULL page HTML for phone via tel: hrefs & regex           ║
║    3. Also check Google Knowledge Panel selectors                        ║
║    No Gemini / DuckDuckGo AI fallback for phone searches.               ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import asyncio
import random
import re
import json
import urllib.parse
from pathlib import Path
from typing import Optional, List, Dict, Any

from playwright.async_api import (
    async_playwright,
    Browser,
    BrowserContext,
    Page,
    TimeoutError as PlaywrightTimeout,
)

import config
from browser.base_agent import BaseBrowserAgent
from utils.anti_bot import (
    get_random_user_agent,
    short_delay,
    is_captcha_page,
    wait_for_human_captcha_solve,
    get_fingerprint_bundle,
    build_cdp_injection_script,
    action_delay_async,
)
from utils.logger import get_logger, alert

logger = get_logger(__name__)

# ── Google Knowledge Panel / Instant Answer selectors ──────────────────────
# These CSS selectors target common locations where Google displays phone numbers
# directly on the search results page (no AI Overview needed).
GOOGLE_PHONE_SELECTORS = [
    # Knowledge Panel phone number
    "[data-attrid='kc:/local:phone'] span",
    "[data-attrid='tel'] span",
    "[data-dtype='d3ph'] span",
    # Business info card
    ".LGOjhe span",
    ".zS8pY",
    # Local pack result phone
    "span[data-dtype='d3ph']",
    # Rich answer / featured snippet
    ".kno-rdesc span",
    ".yDYNvb.lyLwlc",
    # Generic description blocks that may contain phone
    "div[data-attrid='wa:/description'] span",
    "[data-chunk-index='0']",
    ".wDYxhc .VwiC3b",
]

GOOGLE_SEARCH_INPUT = 'textarea[name="q"], input[name="q"]'

# ── Gemini selectors (kept for SIREN/Name enrichment only, NOT phone) ──────
GEMINI_INPUT_SELECTORS   = ["div[role='combobox']", ".ql-editor", "textarea"]
GEMINI_RESPONSE_SELECTORS = [
    ".model-response-text",
    "message-content",
    "div.message-content",
    ".response-container-content",
]


class PlaywrightAgent:
    def __init__(self, worker_id: int = 0):
        self.worker_id = worker_id
        self._playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.current_proxy: Optional[str] = None
        self._lock = asyncio.Lock()
        # Fingerprint bundle — regenerated on each start()
        self._fingerprint = None

        # Generate a unique profile path for this worker to avoid locking conflicts
        self.profile_path = config.CHROMIUM_PROFILE_PATH
        if worker_id > 0:
            original_path = Path(config.CHROMIUM_PROFILE_PATH)
            self.profile_path = str(original_path.parent / (original_path.name + f"_worker_{worker_id}"))

    # ── Lifecycle ──────────────────────────────────────────────────────────

    async def start(self) -> None:
        logger.info("[Playwright] Starting Chrome with your profile (Async)...")
        self._playwright = await async_playwright().start()

        # ── Generate per-session fingerprint bundle (Task 2) ──────────────
        self._fingerprint = get_fingerprint_bundle()
        vp = self._fingerprint["viewport"]
        launch_args = []

        if not config.BROWSER_USE_SANDBOX:
            launch_args.append("--no-sandbox")
            launch_args.append("--disable-setuid-sandbox")

        launch_args.extend([
            "--disable-dev-shm-usage",
            f"--window-size={vp['width']},{vp['height']}",
            "--disable-blink-features=AutomationControlled",
        ])

        geolocation = None
        permissions = []
        if config.SET_GEOLOCATION:
            geolocation = {"latitude": config.DEFAULT_LAT, "longitude": config.DEFAULT_LON}
            permissions = ["geolocation"]

        proxy_settings = None
        if config.PROXY_ENABLED and self.current_proxy:
            proxy_settings = {"server": self.current_proxy}

        self.context = await self._playwright.chromium.launch_persistent_context(
            user_data_dir=self.profile_path,
            headless=False,
            executable_path=config.CHROMIUM_BINARY_PATH or None,
            args=launch_args,
            viewport={"width": vp["width"], "height": vp["height"]},
            user_agent=self._fingerprint["user_agent"],
            geolocation=geolocation,
            permissions=permissions,
            ignore_https_errors=True,
            proxy=proxy_settings,
        )

        # ── Inject fingerprint script before any page JS runs (CDP) ───────
        fp_script = build_cdp_injection_script(self._fingerprint)
        await self.context.add_init_script(script=fp_script)

        self.page = self.context.pages[0] if self.context.pages else await self.context.new_page()
        alert("INFO", "Playwright session started", {
            "worker": self.worker_id,
            "viewport": f"{vp['width']}×{vp['height']}",
        })
        logger.info(
            f"[Playwright] ✅ Ready — fingerprint injected "
            f"({vp['width']}×{vp['height']}, "
            f"UA=...{self._fingerprint['user_agent'][-25:]})"
        )

    async def close(self) -> None:
        try:
            if self.context: await self.context.close()
            if self._playwright: await self._playwright.stop()
        except Exception:
            pass
        finally:
            self.context = self.page = self._playwright = None

    async def rotate_proxy(self) -> None:
        """Fetch a new proxy and restart the browser context."""
        logger.info(f"[Playwright-Worker-{self.worker_id}] ♻️ Rotating proxy...")
        from utils.proxy_manager import get_next_proxy
        new_proxy = get_next_proxy()
        if new_proxy:
            self.current_proxy = new_proxy
            logger.info(f"[Playwright-Worker-{self.worker_id}] New Proxy attached: {new_proxy}")
            await self.close()
            await self.start()
        else:
            logger.warning(f"[Playwright-Worker-{self.worker_id}] No free proxies left. Continuing direct.")

    async def get_page_source(self) -> str:
        return await self.page.content() if self.page else ""

    async def extract_aeo_data(self) -> list:
        """
        Capture script[type="application/ld+json"] tags.
        'Zero-Click' method to extract Schema.org data.
        """
        if not self.page:
            return []
        try:
            # We use locator.all_inner_texts() to get the content of all matching tags
            scripts = await self.page.locator('script[type="application/ld+json"]').all_inner_texts()
            extracted = []
            for s in scripts:
                if not s or not s.strip(): continue
                try:
                    data = json.loads(s)
                    if isinstance(data, dict):
                        extracted.append(data)
                    elif isinstance(data, list):
                        extracted.extend(data)
                except:
                    continue
            return extracted
        except Exception as e:
            logger.debug(f"[Playwright] AEO extraction failed: {e}")
            return []

    async def extract_knowledge_panel_phone(self) -> Optional[str]:
        """
        Implementation of GEMINI.md logic for Playwright.
        """
        if not self.page:
            return None

        # Strategy A: 'd3ph' data attribute
        try:
            # We try both <a> and <span>
            selector = "a[data-dtype='d3ph'], [data-dtype='d3ph']"
            element = self.page.locator(selector).first
            
            # Check aria-label
            aria_label = await element.get_attribute("aria-label")
            if aria_label and "Call phone number" in aria_label:
                logger.info(f"    [Playwright/GEMINI-A] Found phone in aria-label: {aria_label}")
                return aria_label.replace("Call phone number ", "").strip()

            # Fallback text
            text = await element.text_content()
            if text:
                logger.info(f"    [Playwright/GEMINI-A] Found phone in text: {text}")
                return text.strip()
        except:
            pass

        # Strategy B: aria-label scan
        try:
            selector = "[aria-label*='Call phone number']"
            element = self.page.locator(selector).first
            label = await element.get_attribute("aria-label")
            if label:
                logger.info(f"    [Playwright/GEMINI-B] Found phone in generic aria-label.")
                return label.replace("Call phone number ", "").strip()
        except:
            pass

        # Strategy C: Regex on #rhs
        try:
            rhs_locator = self.page.locator("#rhs").first
            rhs_text = await rhs_locator.text_content()
            if rhs_text:
                phone_match = re.search(r'(\+?[0-9\s\.]{8,20})', rhs_text)
                if phone_match:
                    logger.info(f"    [Playwright/GEMINI-C] Found phone in RHS panel text.")
                    return phone_match.group(0).strip()
        except:
            pass

        return None

    # ── Main Search Method (phone-focused, NO AI/LLM) ─────────────────────

    async def search_google_ai(self, query: str) -> Optional[str]:
        """
        Perform a Google search, activate AI Mode tab, then extract content.
        Returns the page's text content, or None.
        """
        if not self.page:
            return None
        async with self._lock:
            try:
                await self._navigate_and_search(query)  # Includes _click_ai_mode_tab()

                # Wait for results page
                await asyncio.sleep(2)
                await self.page.wait_for_load_state("domcontentloaded")
                await self._handle_captcha_if_present()

                # ─ Try targeted phone selectors first (Knowledge Panel) ─
                phone_text = await self._extract_first_available(GOOGLE_PHONE_SELECTORS, timeout_ms=3000)
                if phone_text:
                    logger.info(f"✨ [Google] Found phone in Knowledge Panel.")
                    return phone_text

                # ─ Return FULL page TEXT (not HTML) for regex scanning ─
                logger.info("[Google] No instant panel — returning page text for regex scan.")
                try:
                    return await self.page.inner_text("body")
                except:
                    return await self.page.content()

            except Exception as e:
                logger.error(f"[Google] Error: {e}")
                return None

    async def submit_google_search(self, query: str) -> bool:
        """
        Navigate to Google and submit the search query.
        Returns True if successful, False if blocked (CAPTCHA).
        """
        if not self.page:
            return False
        async with self._lock:
            try:
                await self.page.goto(config.GOOGLE_URL, wait_until="load")
                await asyncio.sleep(1)
                
                await self._handle_google_cookies()
                await self._handle_captcha_if_present()

                search_box = await self._find_input(GOOGLE_SEARCH_INPUT)
                if search_box:
                    await search_box.click()
                    await self._human_type_playwright(query)
                    await search_box.press("Enter")
                    return True
                return False
            except Exception as e:
                logger.error(f"[Google] Search Submission Error: {e}")
                return False

    async def _navigate_and_search(self, query: str) -> None:
        logger.info(f"[Google] Search: {query}")
        await self.page.goto(config.GOOGLE_URL, wait_until="load")
        await asyncio.sleep(1)
        
        await self._handle_google_cookies()
        await self._handle_captcha_if_present()

        search_box = await self._find_input(GOOGLE_SEARCH_INPUT)
        if search_box:
            await search_box.click()
            await self._human_type_playwright(query)
            await search_box.press("Enter")
            await asyncio.sleep(2)
            # ⭐ ALWAYS try to activate AI Mode tab after every search
            await self._click_ai_mode_tab()

    async def _click_ai_mode_tab(self) -> bool:
        """
        Clicks the 'Mode IA' tab that appears in Google search results.
        As seen in the user's screenshot, the tab is labelled 'Mode IA' in French.
        Tries multiple selectors to be robust across regions/languages.
        """
        if not self.page:
            return False

        # Selectors ranked by specificity — French first (user's region)
        tab_selectors = [
            "a:has-text('Mode IA')",
            "a:has-text('IA')",
            "div[role='tab']:has-text('Mode IA')",
            "div[role='tab']:has-text('IA')",
            "a:has-text('AI Mode')",
            "a:has-text('AI')",
            "a:has-text('Conversations')",
        ]

        for selector in tab_selectors:
            try:
                tab = self.page.locator(selector).first
                if await tab.count() > 0 and await tab.is_visible(timeout=1500):
                    await tab.click()
                    logger.info(f"🤖 [AI Mode Tab] Clicked: '{selector}'")
                    await asyncio.sleep(2.5)  # Wait for AI results to load
                    return True
            except:
                continue

        logger.debug("[AI Mode Tab] Tab not found — using standard results.")
        return False


    async def goto_url(self, url: str) -> bool:
        """Navigate to a specific URL."""
        if not self.page: return False
        async with self._lock:
            try:
                await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                return True
            except Exception as e:
                logger.debug(f"[Playwright] Failed to visit {url}: {e}")
                return False

    async def crawl_website(self, url: str) -> str:
        """
        Deep crawl of a website:
        1. Visit homepage.
        2. Identify contact/about links.
        3. Visit them and collect all text.
        """
        if not self.page: return ""
        
        async with self._lock:
            try:
                logger.info(f"🕸️ [Playwright] DeepCrawl starting: {url}")
                await self.page.goto(url, wait_until="domcontentloaded", timeout=15000)
                await asyncio.sleep(2)
                
                all_text = [f"--- PAGE: {url} ---\n" + await self.page.inner_text("body")]
                
                # Link discovery for contact pages
                links = await self.page.locator("a").all()
                found_sublinks = []
                
                for link in links:
                    name = (await link.inner_text() or "").lower()
                    href = (await link.get_attribute("href") or "").lower()
                    
                    if any(k in name or k in href for k in config.CONTACT_KEYWORDS):
                        full_url = await link.get_attribute("href")
                        if full_url and full_url.startswith("http") and full_url != url:
                            found_sublinks.append(full_url)
                        elif full_url and full_url.startswith("/"):
                            # Handle relative paths
                            from urllib.parse import urljoin
                            found_sublinks.append(urljoin(url, full_url))
                    
                    if len(found_sublinks) >= 2: break # Max 2 subpages

                # Visit subpages
                for sub in list(set(found_sublinks)):
                    try:
                        logger.info(f"   ∟ Visiting subpage: {sub}")
                        await self.page.goto(sub, wait_until="domcontentloaded", timeout=10000)
                        await asyncio.sleep(1)
                        all_text.append(f"\n--- PAGE: {sub} ---\n" + await self.page.inner_text("body"))
                    except:
                        continue
                
                return "\n".join(all_text)

            except Exception as e:
                logger.error(f"[Playwright] Crawl error for {url}: {e}")
                return ""

    # ── OLD: _activate_ia_mode (kept as comment for reference) ──
    # async def _activate_ia_mode(self) -> bool:
    #     """Attempts to find and activate the IA Mode tab by clicking."""
    #     selectors = ["a:has-text('IA')", "a:has-text('Mode IA')", ...]
    #     for s in selectors:
    #         btn = self.page.locator(s).first
    #         if await btn.count() > 0 and await btn.is_visible():
    #             await btn.click()
    #             return True
    #     return False

    # ── OLD: search_google_ia_mode (kept as comment for reference) ──
    # async def search_google_ia_mode(self, query: str) -> Optional[str]:
    #     """Navigated normally then clicked the IA tab."""
    #     await self._navigate_and_search(query)
    #     activated = await self._activate_ia_mode()
    #     ...

    async def search_google_ai_mode(self, prompt: str) -> Optional[str]:
        """
        ⭐ PRIMARY SEARCH METHOD — TIER 0
        
        Navigates directly to Google AI Mode using the aep=42 URL parameter
        (as demonstrated by the user's screenshot). This is the fastest and
        most reliable approach — one query returns a full JSON response.
        
        Steps:
        1. Encode the prompt and navigate to the AI Mode URL directly.
        2. Wait for Google AI to finish streaming its response.
        3. Extract the JSON code block from the page.
        4. Return the raw JSON string.
        """
        if not self.page:
            return None
        
        async with self._lock:
            try:
                import urllib.parse
                encoded = urllib.parse.quote_plus(prompt)
                ai_mode_url = config.GOOGLE_AI_MODE_URL + encoded
                
                logger.info(f"🤖 [AI Mode] Navigating to: {ai_mode_url}")
                await self.page.goto(ai_mode_url, wait_until="load", timeout=30000)
                await asyncio.sleep(2)
                
                await self._handle_google_cookies()
                await self._handle_captcha_if_present()
                
                # Wait for the AI response to finish streaming
                # Google AI Mode renders a code block with the JSON
                logger.info("⏳ [AI Mode] Waiting for AI response to stream...")
                response_text = await self._wait_for_ai_mode_response(timeout_sec=25)
                
                if response_text:
                    logger.info(f"✨ [AI Mode] Got response ({len(response_text)} chars)")
                else:
                    logger.warning("[AI Mode] No AI response detected, falling back.")
                
                return response_text
                
            except Exception as e:
                logger.error(f"[AI Mode] Error: {e}")
                return None

    async def _wait_for_ai_mode_response(self, timeout_sec: int = 25) -> Optional[str]:
        """
        Waits for Google AI Mode to finish streaming and extracts all text output.
        Tries multiple selectors used by Google's AI Mode interface.
        Uses a "stable output" check — waits until the content stops changing.
        """
        if not self.page:
            return None
        
        # Selectors for the AI Mode response container (ranked by specificity)
        ai_response_selectors = [
            "code",                          # JSON code blocks
            ".kp-wholepage-osrp-ent",        # Knowledge panel entity
            "div.mod",                       # AI response containers
            ".xpdopen .c2xzTb",              # Featured snippet with code
            "[data-attrid='wa:/description']",
            "div[role='main'] div.VwiC3b",  # Result description block
            "div[jsname='yEVEwb']",          # AI overview container
            "div[class*='osrp']",            # AI mode outer container
        ]
        
        deadline = asyncio.get_event_loop().time() + timeout_sec
        prev_text = ""
        stable_count = 0
        
        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(1.5)
            
            # Try to extract content from each selector
            for selector in ai_response_selectors:
                try:
                    elements = await self.page.locator(selector).all()
                    texts = []
                    for el in elements[:5]:  # max 5 elements per selector
                        t = await el.inner_text()
                        if t and len(t) > 30:
                            texts.append(t)
                    
                    if texts:
                        combined = "\n".join(texts)
                        # Check if output has stabilised (stopped streaming)
                        if combined == prev_text:
                            stable_count += 1
                            if stable_count >= 2:  # Stable for 2 cycles = done
                                return combined
                        else:
                            prev_text = combined
                            stable_count = 0
                        break  # Found content, keep checking this selector
                except:
                    continue
        
        # Return whatever we have even if not fully stable
        return prev_text if prev_text else None

    @staticmethod
    def parse_ai_mode_json(raw_text: str) -> dict:
        """
        Extracts and parses the JSON block from Google AI Mode's response.
        Handles cases where JSON is wrapped in a code block or has leading text.
        Returns a dict with all extracted fields, or an empty dict.
        """
        if not raw_text:
            return {}
        
        # Strategy A: find a ```json ... ``` code block
        code_match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', raw_text, re.DOTALL)
        if code_match:
            try:
                return json.loads(code_match.group(1))
            except:
                pass
        
        # Strategy B: find the outermost { } JSON object
        brace_match = re.search(r'\{[\s\S]*\}', raw_text)
        if brace_match:
            try:
                return json.loads(brace_match.group(0))
            except:
                pass
        
        # Strategy C: parse line by line for key: value patterns
        result = {}
        phone_match = re.findall(r'(?:phone|tél[^:]*)[:\s]+([\+0-9][\d\s\.\-]{7,18})', raw_text, re.IGNORECASE)
        if phone_match:
            result["phone_numbers"] = [p.strip() for p in phone_match]
        
        email_match = re.search(r'[\w.\-]+@[\w.\-]+\.\w+', raw_text)
        if email_match:
            result["email"] = email_match.group(0)
        
        siren_match = re.search(r'\b(\d{9})\b', raw_text)
        if siren_match:
            result["siren"] = siren_match.group(1)
        
        return result

    async def _handle_google_cookies(self) -> None:
        """Handle 'Accept all' cookie buttons if present."""
        try:
            selectors = [
                "button:has-text('Accept all')", 
                "button:has-text('Accepter tout')", 
                "button:has-text('I agree')",
                "#L2AGLb" # Specific ID for Google Accept button
            ]
            for s in selectors:
                btn = self.page.locator(s)
                if await btn.count() > 0 and await btn.is_visible():
                    await btn.click()
                    logger.info("[Playwright] Cookie consent accepted.")
                    await asyncio.sleep(1)
                    break
        except:
            pass

    async def _handle_captcha_if_present(self) -> None:
        if is_captcha_page(await self.page.content()):
            logger.warning("[Google] CAPTCHA detected.")
            logger.info(f"Waiting for CAPTCHA to be manually resolved ({config.CAPTCHA_WAIT_SECONDS}s)...")
            await asyncio.sleep(config.CAPTCHA_WAIT_SECONDS)

    async def search_gemini_ai(self, query: str) -> Optional[str]:
        """
        Deep search using Google Gemini.
        """
        if not self.page:
            return None
        async with self._lock:
            try:
                logger.info(f"🚀 [Gemini] DeepSearch (enrichment only): {query}")
                await self.page.goto(config.GEMINI_URL, wait_until="load")
                await asyncio.sleep(4)

                chat_input = None
                for s in GEMINI_INPUT_SELECTORS:
                    chat_input = await self._find_input(s, timeout_ms=5000)
                    if chat_input:
                        break

                if not chat_input:
                    logger.warning("[Gemini] Could not find input area.")
                    return None

                await chat_input.click()
                await self._human_type_playwright(query)
                await self.page.keyboard.press("Enter")

                return await self._wait_for_streaming_response(GEMINI_RESPONSE_SELECTORS, stable_wait_sec=4)
            except Exception as e:
                logger.error(f"[Gemini] Error: {e}")
                return None

    # ── Private Helpers ────────────────────────────────────────────────────

    async def _find_input(self, selector: str, timeout_ms: int = 10000):
        try:
            await self.page.wait_for_selector(selector, timeout=timeout_ms)
            return self.page.locator(selector).first
        except Exception:
            return None

    async def _extract_first_available(self, selectors: list, timeout_ms: int = 3000) -> Optional[str]:
        """Try each selector; return the first non-empty text found."""
        for s in selectors:
            try:
                await self.page.wait_for_selector(s, timeout=timeout_ms, state="visible")
                text = await self.page.locator(s).first.text_content()
                if text and text.strip():
                    return text.strip()
            except Exception:
                continue
        return None

    async def _human_type_playwright(self, text: str) -> None:
        for char in text:
            await self.page.keyboard.type(char)
            await asyncio.sleep(random.uniform(0.04, 0.12))

    async def _wait_for_streaming_response(self, selectors: list, stable_wait_sec: int = 4) -> Optional[str]:
        start = asyncio.get_event_loop().time()
        last_text = ""
        stable_count = 0
        while asyncio.get_event_loop().time() - start < 60:
            current = await self._extract_first_available(selectors, timeout_ms=3000) or ""
            if current and current == last_text:
                stable_count += 1
                if stable_count >= stable_wait_sec:
                    return current
            else:
                stable_count = 0
                last_text = current
            await asyncio.sleep(1)
        return last_text or None
