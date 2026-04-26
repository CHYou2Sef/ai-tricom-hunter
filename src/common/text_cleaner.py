"""
╔══════════════════════════════════════════════════════════════════════════╗
║  common/text_cleaner.py                                                  ║
║                                                                          ║
║  HTML → Plain Text Sanitizer                                             ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Strips HTML markup, scripts, and styles to produce clean text         ║
║    suitable for downstream LLM processing or regex extraction.           ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    1. Removes <script> and <style> blocks (including contents)           ║
║    2. Strips all remaining HTML tags                                     ║
║    3. Collapses multiple whitespace/newlines into single spaces          ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re


def clean_html_to_text(html: str) -> str:
    """
    Remove scripts, styles, and other noise from HTML to get clean, human-readable text.

    Args:
        html: Raw HTML string (may include scripts, styles, tags)

    Returns:
        str: Clean plain text with all markup removed
    """
    if not html:
        return ""
    
    # Remove script and style tags
    cleaner = re.sub(r'<script.*?>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    cleaner = re.sub(r'<style.*?>.*?</style>', ' ', cleaner, flags=re.DOTALL | re.IGNORECASE)
    
    # Remove all other HTML tags
    cleaner = re.sub(r'<.*?>', ' ', cleaner)
    
    # Replace multiple spaces/newlines with single ones
    cleaner = re.sub(r'\s+', ' ', cleaner)
    
    return cleaner.strip()
