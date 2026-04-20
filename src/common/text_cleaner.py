import re

def clean_html_to_text(html: str) -> str:
    """
    Remove scripts, styles, and other noise from HTML to get clean, human-readable text.
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
