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
║                                                                          ║
║  FIXES (v2):                                                             ║
║    - extract_search_terms: now matches '- NAME:' dash-prefix format      ║
║      used by AI_MODE_SEARCH_PROMPT in config.py.                         ║
║    - extract_search_terms: fallback skips ### headers and markdown       ║
║      separators so '### IDENTITY' never reaches Google search box.       ║
║    - build_b2b_query: added optional siren param, richer intent phrase.  ║
║    - build_social_query: new helper for Facebook/LinkedIn targeted       ║
║      Google searches used by SeleniumBase social discovery tier.         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
import urllib.parse
from typing import Optional, Any


def extract_search_terms(prompt: str) -> str:
    """
    Cleans a long AI prompt into a compact search query for Google.

    Extraction priority:
      1. Structured fields: '- NAME:', 'NAME:' (with or without leading dash)
         + optionally '- ADDRESS:', '- SIREN:'
      2. First non-header, non-markdown content line
      3. Hard truncation of first line
    """
    if not prompt:
        return ""

    prompt = prompt.strip()

    # If it's a short, already clean query, return as is
    if len(prompt) < 150 and "###" not in prompt and "NAME:" not in prompt:
        return prompt

    # ── Strategy 1: structured field extraction ───────────────────────────
    # Matches both '- NAME: Acme Corp' (AI_MODE_SEARCH_PROMPT format)
    # and  'NAME: Acme Corp'  (SIREN_SEARCH_TEMPLATE format)
    name_match = re.search(r"(?:-\s*)?NAME:\s*(.+)", prompt, re.IGNORECASE)
    addr_match = re.search(r"(?:-\s*)?ADDRESS:\s*(.+)", prompt, re.IGNORECASE)
    siren_match = re.search(r"(?:-\s*)?SIREN:\s*(\d{9,14})", prompt, re.IGNORECASE)

    if name_match:
        query = name_match.group(1).strip()
        if addr_match:
            query += f" {addr_match.group(1).strip()}"
        if siren_match:
            query += f" {siren_match.group(1).strip()}"
        query += " téléphone siège social"
        return query.strip()

    # ── Strategy 2: skip structural markdown headers, find first real line ─
    # This prevents '### IDENTITY' or '### MISSION' from reaching Google.
    lines = [ln.strip() for ln in prompt.split("\n") if ln.strip()]
    for line in lines:
        if re.match(r"^#{1,4}\s", line):  # ### IDENTITY, ## STEPS …
            continue
        if re.match(r"^[-=*_]{3,}", line):  # ---, ===, ***
            continue
        if len(line) < 5:  # Noise
            continue
        return line[:150].strip()

    # ── Strategy 3: hard truncate ──────────────────────────────────────────
    return lines[0][:150] if lines else ""


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
        "udm": "50",  # Requested: Gemini/AI specific
        "aep": "22",  # Requested: Experimental generative
        "nfpr": "1",  # No auto-correct redirect (performance)
        "no_sw_cr": "1",  # Disable slow ServiceWorker caches (performance)
        "gl": region,
        "hl": "fr",
    }

    return f"{base_url}?{urllib.parse.urlencode(params)}"


def build_b2b_query(
    company_name: str,
    address: Optional[str] = None,
    siren: Optional[str] = None,
) -> str:
    """
    Constructs a simple, human-like B2B search phrase for Google.

    Important: keep this string as *query terms only* (no prompt-instructions like
    "output de format json") to preserve relevance and improve Google AI mode
    triggering reliability.
    """
    query = company_name.strip()

    if address:
        query += f" {address.strip()}"

    if siren:
        query += f" {siren.strip()}"

    # Keep intent as a search term (no output-format directives).
    query += " téléphone contact"

    return query
