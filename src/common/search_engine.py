"""
Strategic Search Engine Utility - AI Tricom Hunter
Centralized logic for generating "Power Search" URLs (Google AI Mode).
"""
import urllib.parse
from typing import Optional

def generate_google_ai_url(query: str, region: str = "fr") -> str:
    """
    Generates a Google Search URL optimized for triggering the 
    AI Overview (Search Generative Experience).
    
    Parameters:
    - udm=14: Forces 'AI Overview' or 'Search Labs' layout.
    - aep=42: Advanced experimental parameter for generative UI.
    - q: The encoded search query.
    """
    base_url = f"https://www.google.com/search"
    params = {
        "q": query,
        "udm": "14",    # The 'AI Overview' magic flag
        "aep": "42",    # Experimental generative flag
        "gl": region,   # Geo-location for accuracy (e.g., 'fr')
        "hl": "fr",     # Interface language
    }
    
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def build_b2b_query(company_name: str, address: Optional[str] = None) -> str:
    """
    Constructs a high-precision B2B query to find contact details.
    """
    query = f'"{company_name}"'
    if address:
        query += f' "{address}"'
    
    # "Caveman" style keyword additives for phone extraction
    query += ' ("téléphone" OR "contact" OR "siège social")'
    query += ' site:pappers.fr OR site:societe.com OR site:societe.ninja OR site:linkedin.com'
    
    return query
