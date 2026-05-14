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

import re
import urllib.parse
from typing import Optional, Any

def extract_search_terms(prompt: str) -> str:
    """
    Cleans a long AI prompt into a compact search query for Google.
    Extracts NAME and ADDRESS if present, otherwise truncates the prompt.
    """
    if not prompt:
        return ""
        
    prompt = prompt.strip()
    
    # If it's a short, already clean query, return as is
    if len(prompt) < 150 and "###" not in prompt and "NAME:" not in prompt:
        return prompt

    # Try to extract structured fields from the multi-line prompt
    name_match = re.search(r"NAME:\s*(.*)", prompt, re.IGNORECASE)
    addr_match = re.search(r"ADDRESS:\s*(.*)", prompt, re.IGNORECASE)
    
    if name_match:
        query = name_match.group(1).strip()
        if addr_match:
            query += f" {addr_match.group(1).strip()}"
        return query
        
    # Fallback: take first 150 chars or until first newline
    lines = prompt.split('\n')
    first_line = lines[0].strip()
    if len(first_line) > 150:
        return first_line[:150].strip()
    return first_line

def generate_google_ai_url(query: str, region: str = "fr") -> str:
    """
    Generates a Google Search URL optimized for triggering the 
    AI Overview (Search Generative Experience / Gemini in Search).
    """
    # Ensure query is cleaned if it looks like a complex prompt
    clean_query = extract_search_terms(query)
    
    base_url = f"https://www.google.com/search"
    params = {
        "q": clean_query,
        "udm": "50",    # Requested: Gemini/AI specific
        "aep": "22",    # Requested: Experimental generative
        "nfpr": "1",    # No auto-correct redirect (performance)
        "no_sw_cr": "1",# Disable slow ServiceWorker caches (performance)
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
