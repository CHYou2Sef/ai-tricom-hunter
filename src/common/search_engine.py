"""
╔══════════════════════════════════════════════════════════════════════════╗
║  common/search_engine.py                                                 ║
║                                                                          ║
║  Strategic Search URL Generator for Google AI Mode                       ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Centralizes the logic for building "Power Search" URLs that trigger   ║
║    Google's AI Overview / Search Generative Experience (SGE).            ║
║                                                                          ║
║  PARAMETERS EXPLAINED:                                                   ║
║    udm=50  : Direct AI Overview / Gemini variant (requested by user)    ║
║    aep=22  : Experimental generative UI parameter                       ║
║    gl=fr   : Geolocation lock to France for accurate results            ║
║    hl=fr   : Interface language = French                                ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import urllib.parse
from typing import Optional

def generate_google_ai_url(query: str, region: str = "fr") -> str:
    """
    Generates a Google Search URL optimized for triggering the 
    AI Overview (Search Generative Experience / Gemini in Search).
    
    Parameters (Updated for user request):
    - udm=50: Direct AI Overview / Gemini variant.
    - aep=22: Experimental generative UI parameter.
    """
    base_url = f"https://www.google.com/search"
    params = {
        "q": query,
        "udm": "50",    # Requested: Gemini/AI specific
        "aep": "22",    # Requested: Experimental generative
        "gl": region,
        "hl": "fr",
    }
    
    return f"{base_url}?{urllib.parse.urlencode(params)}"

def build_b2b_query(company_name: str, address: Optional[str] = None) -> str:
    """
    Constructs a simple, human-like search phrase for the search bar.
    Avoids complex prompts/operators to prevent triggering anti-bot UI.
    """
    query = f"{company_name}"
    if address:
        query += f" {address}"
    
    # Just a simple intent hint instead of complex OR logic
    query += " téléphone contact"
    
    return query
