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

from utils.anti_bot import wait_for_human_captcha_solve
from utils.anti_bot import is_captcha_page
from utils.anti_bot import get_fingerprint_bundle
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

    async def _handle_captcha_if_present(self) -> bool:
        """Shared CAPTCHA detection logic."""
        if not self._page: return False
        
        source = await self.get_page_source()
        if is_captcha_page(source):
            return wait_for_human_captcha_solve()
        return True

    async def get_page_source(self) -> str:
        """To be implemented by child classes."""
        raise NotImplementedError

    async def close(self):
        """Standardized close method."""
        if self._browser:
            try:
                await self._browser.close()
            except:
                pass
        self._browser = None
        self._page = None
