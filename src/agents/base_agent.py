"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/base_agent.py                                                   ║
║                                                                          ║
║  Abstract base class for browser agents.                                 ║
║  Both NodriverAgent and PatchrightAgent inherit from this class.          ║
║                                                                          ║
║  BEGINNER NOTE:                                                          ║
║    An "abstract base class" (ABC) is a template that forces all          ║
║    subclasses to implement specific methods.                             ║
║    Think of it as a contract: "You MUST implement these methods."        ║
║    This ensures Selenium and Playwright agents have the same API.        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from __future__ import annotations
from typing import Optional, Any, Dict, List, TYPE_CHECKING
import os
from common.anti_bot import wait_for_human_captcha_solve
from common.anti_bot import is_captcha_page
from common.anti_bot import get_fingerprint_bundle
from core.logger import get_logger

logger = get_logger(__name__)
class BaseBrowserAgent:
    """
    Lean base class for all browser-based agents (Playwright, Nodriver).
    Handles shared logic: Fingerprints, CAPTCHAs, and API consistency.
    """
    def __init__(self, worker_id: int = 0):
        self.worker_id = worker_id
        self._fingerprint = get_fingerprint_bundle()
        self._page = None
        self._browser = None
        self._last_content: str = ""

    async def _handle_captcha_if_present(self) -> bool:
        """Shared CAPTCHA detection logic."""
        if not self._page: 
            logger.info("No page found")
            return False
        
        source = await self.get_page_source()
        if is_captcha_page(source):
            logger.info("CAPTCHA found")
            return wait_for_human_captcha_solve()
        return True

    async def report_proxy_error(self, proxy: Optional[str], status_code: int = 403) -> None:
        """
        Standardized proxy error reporting to the central ProxyManager.
        
        Args:
            proxy: The proxy string that failed.
            status_code: HTTP status code (default 403 for blocks).
        """
        if not proxy:
            return
            
        try:
            from common.proxy_manager import report_proxy_error
            await report_proxy_error(proxy, status_code)
            logger.warning(f"[{self.__class__.__name__}] 🚩 Reported proxy error ({status_code}) for: {proxy}")
        except Exception as e:
            logger.error(f"Error reporting proxy failure: {e}")

    def is_block_response(self, content: Any) -> bool:
        """
        Check content or exception for common blocking/WAF signatures.
        
        Args:
            content: Can be a string (page source), an Exception object, or an int (status code).
        """
        if not content:
            return False
            
        # Handle status codes directly
        if isinstance(content, int):
            return content in [403, 429, 503, 999]
            
        # Convert content/exception to string for robust matching
        text = str(content).lower()
        
        block_terms = [
            "forbidden", "access denied", "blocked", "captcha", 
            "security challenge", "too many requests", "403 forbidden",
            "bot detection", "automated access", "err_tunnel", "err_proxy",
            "connection refused", "timeout", "ssl", "certificate", "429",
            "ip_ban", "waf", "rate limit", "cloudflare"
        ]
        return any(term in text for term in block_terms)

    async def get_page_source(self) -> str:
        """To be implemented by child classes."""
        raise NotImplementedError

    async def extract_universal_data(self) -> Optional[dict]:
        """
        New V6 Elite extraction pattern.
        Gets the page source and delegates all parsing to the Universal Unified Extractor (UUE).
        Ensures 100% parity across Nodriver, Patchright, Crawl4AI, and Camoufox.
        """
        source = await self.get_page_source()
        if not source:
            return None
            
        from common.universal_extractor import UniversalExtractor
        metadata = UniversalExtractor.extract_all(source)
        
        # If the Universal Extractor found NO data, return None so the HybridEngine properly escalates
        has_data = any([
            metadata.get("aeo_data"),
            metadata.get("heuristic_phones"),
            metadata.get("heuristic_emails"),
            metadata.get("semantic_phones"),
            any(metadata.get("social_links", {}).values() if metadata.get("social_links") else []) # Added safety check
        ])
        if not has_data:
            return None
            
        return metadata

    async def close(self):
        """Standardized close method."""
        if self._browser:
            try:
                await self._browser.close()
            except:
                pass
        self._browser = None
        self._page = None
    async def generate_human_noise(self) -> None:
        """
        Navigate to a random 'Trust Site' to build profile history and reduce bot signals.
        To be implemented by specific agent tiers.
        """
        pass

    async def search_google_ai_mode(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """
        AI Mode search via browser waterfall.
        To be implemented by child classes.
        """
        raise NotImplementedError

    async def search_google_ai(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """
        Legacy AI search fallback.
        To be implemented by child classes.
        """
        raise NotImplementedError

    async def search_google_ai_interactive(self, prompt: str, ai_mode_url: Optional[str] = None, row: Optional[Any] = None) -> Optional[str]:
        """
        Interactive high-stealth search flow (Google.com -> type query -> Enter -> Click AI).
        To be implemented by child classes.
        """
        raise NotImplementedError

    async def is_alive(self) -> bool:
        """
        Check if the browser agent and its underlying process are still healthy.
        To be implemented by child classes.
        """
        raise NotImplementedError
