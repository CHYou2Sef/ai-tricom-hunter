"""
╔══════════════════════════════════════════════════════════════════════════╗
║  browser/base_agent.py                                                   ║
║                                                                          ║
║  Abstract base class for browser agents.                                 ║
║  Both SeleniumAgent and PlaywrightAgent inherit from this class.         ║
║                                                                          ║
║  BEGINNER NOTE:                                                          ║
║    An "abstract base class" (ABC) is a template that forces all          ║
║    subclasses to implement specific methods.                             ║
║    Think of it as a contract: "You MUST implement these methods."        ║
║    This ensures Selenium and Playwright agents have the same API.        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

from abc import ABC, abstractmethod
from typing import Optional, List


class BaseBrowserAgent(ABC):
    """
    Abstract browser agent.
    All concrete browser implementations must inherit from this class
    and implement all @abstractmethod methods.
    """

    # ─────────────────────────────────────────────────────────────────────
    # LIFECYCLE METHODS
    # ─────────────────────────────────────────────────────────────────────

    @abstractmethod
    def start(self) -> None:
        """
        Launch the browser and open a new window.
        Must be called before any search methods.
        """
        ...

    @abstractmethod
    def close(self) -> None:
        """
        Close the browser window and clean up resources.
        Always call this when done, even on error.
        """
        ...

    # ─────────────────────────────────────────────────────────────────────
    # SEARCH METHODS
    # ─────────────────────────────────────────────────────────────────────

    @abstractmethod
    def search_google_ai(self, query: str) -> Optional[str]:
        """
        Submit `query` to Google's AI bar (AI Overviews / SGE).

        Args:
            query : The search string (e.g. "Numéro de téléphone ACME Paris")

        Returns:
            The text content of the AI answer, or None if:
            - CAPTCHA blocked
            - No AI answer appeared
            - Any error occurred
        """
        ...

    @abstractmethod
    def search_gemini_ai(self, query: str) -> Optional[str]:
        """
        Submit `query` to Google Gemini (gemini.google.com).

        Args:
            query : The search string

        Returns:
            The text content of Gemini's response, or None on failure.
        """
        ...

    @abstractmethod
    def get_page_source(self) -> str:
        """Return the current page's full HTML source."""
        ...

    @abstractmethod
    def extract_aeo_data(self) -> list:
        """Extract JSON-LD (Schema.org) structured data from the current page."""
        ...

    @abstractmethod
    def extract_knowledge_panel_phone(self) -> Optional[str]:
        """
        Extract business phone number from Google's knowledge panel using
        specific CSS selectors and strategies (from GEMINI.md).
        """
        ...

    @abstractmethod
    def submit_google_search(self, query: str) -> bool:
        """
        Navigate to Google and submit the search query.
        Returns True if successful, False if blocked (CAPTCHA).
        """
        ...

    @abstractmethod
    def goto_url(self, url: str) -> bool:
        """
        Navigate directly to a URL.
        Returns True if successful, False on error.
        """
        ...

    # ─────────────────────────────────────────────────────────────────────
    # UTILITY METHODS (shared implementation via concrete methods)
    # ─────────────────────────────────────────────────────────────────────

    def search_with_fallback(
        self,
        query: str,
        primary: str = "google",
    ) -> Optional[str]:
        """
        Try the primary search engine first.
        If it fails (returns None), try the fallback engine.

        Args:
            query   : The search string
            primary : "google" or "duckduckgo"

        Returns:
            AI response text, or None if both engines failed.

        BEGINNER NOTE:
            This is the main method the agent calls for each row.
            It abstracts away which engine is being used.
        """
        import config

        if primary == "google":
            result = self.search_google_ai(query)
            if result is None:
                result = self.search_duckduckgo_ai(query)
        else:
            result = self.search_duckduckgo_ai(query)
            if result is None:
                result = self.search_google_ai(query)

        return result

    def benchmark(self, test_query: str = "Numéro de téléphone Mairie de Paris") -> float:
        """
        Run a single test search and return the elapsed time in seconds.
        Used by the benchmark module to compare Selenium vs Playwright.

        Args:
            test_query : A simple query to benchmark with

        Returns:
            Elapsed seconds (float)
        """
        import time
        start = time.perf_counter()
        self.start()
        try:
            self.search_google_ai(test_query)
        finally:
            self.close()
        return time.perf_counter() - start
