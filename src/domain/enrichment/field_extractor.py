"""
╔══════════════════════════════════════════════════════════════════════════╗
║  domain/enrichment/field_extractor.py                                    ║
║                                                                          ║
║  AI Response Field Extractor                                             ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Parses raw AI text/HTML responses and extracts structured fields:     ║
║    email, website, SIRET, NAF, director, social media, etc.              ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    1. Tries JSON extraction first (most reliable)                        ║
║    2. Falls back to regex patterns for each field type                   ║
║    3. Validates extracted values (e.g., email format, SIRET length)      ║
║    4. Returns dict with field_name → {value, source, confidence}         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
from typing import Optional


# ── Confidence constants by pattern reliability ──
HIGH   = 0.90
MEDIUM = 0.70
LOW    = 0.45


def extract_all(text: str) -> dict:
    """
    Master function. Run all extractors on a raw AI text block.
    Returns a flat dict: { field_name: (value, confidence) }
    Only returns fields where something was found.
    """
    results = {}

    def _try(key, fn):
        val = fn(text)
        if val:
            results[key] = val  # val is (value, confidence) tuple

    _try("siren",           extract_siren)
    _try("siret",           extract_siret)
    _try("naf",             extract_naf)
    _try("email",           extract_email)
    _try("website",         extract_website)
    _try("forme_juridique", extract_forme_juridique)
    _try("capital",         extract_capital)
    _try("dirigeant",       extract_dirigeant)
    _try("code_postal",     extract_code_postal)
    _try("ville",           extract_ville)
    _try("effectif",        extract_effectif)
    _try("linkedin",        extract_linkedin)
    _try("facebook",        extract_facebook)
    _try("instagram",       extract_instagram)
    _try("twitter",         extract_twitter)

    return results


def extract_siren(text: str) -> Optional[tuple]:
    """9-digit SIREN, not followed by more digits (would make it SIRET)."""
    match = re.search(r'\b(\d{9})\b(?!\s*\d)', text)
    if match:
        return (match.group(1), HIGH)
    return None


def extract_siret(text: str) -> Optional[tuple]:
    """14-digit SIRET."""
    match = re.search(r'\b(\d{14})\b', text)
    if match:
        return (match.group(1), HIGH)
    return None


def extract_naf(text: str) -> Optional[tuple]:
    """NAF/APE code: 4 digits + 1 letter (e.g. 6820A, 4711D)."""
    match = re.search(r'\b(\d{4}[A-Z])\b', text)
    if match:
        return (match.group(1), HIGH)
    return None


def extract_email(text: str) -> Optional[tuple]:
    """Standard email address pattern."""
    match = re.search(
        r'\b([a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,})\b', text
    )
    if match:
        return (match.group(1).lower(), HIGH)
    return None


def extract_website(text: str) -> Optional[tuple]:
    """URL starting with http/https or www."""
    match = re.search(
        r'(https?://[^\s"\'<>]+\.[a-zA-Z]{2,}[^\s"\'<>]*)',
        text
    )
    if match:
        url = match.group(1)
        # Exclude known search/social/schema domains — they are not the company's site
        noise = [
            'google.', 'bing.', 'facebook.', 'linkedin.', 'twitter.', 'x.com',
            'youtube.', 'instagram.', 'pages.jaunes', 'societe.com', 'pappers.fr', 
            'infogreffe', 'schema.org', 'gstatic.com', 'googletagmanager'
        ]
        if not any(n in url.lower() for n in noise):
            # Clean trailing punctuation from URL
            url = url.rstrip('.,;)]}')
            return (url, MEDIUM)
    return None


def extract_forme_juridique(text: str) -> Optional[tuple]:
    """Legal form keywords (French)."""
    forms = [
        'SAS', 'SARL', 'SA', 'EURL', 'SCI', 'SNC', 'SASU',
        'EI', 'EIRL', 'GIE', 'Association loi 1901', 'SCOP'
    ]
    for form in forms:
        if re.search(r'\b' + re.escape(form) + r'\b', text, re.IGNORECASE):
            return (form.upper(), MEDIUM)
    return None


def extract_capital(text: str) -> Optional[tuple]:
    """Capital social amount (e.g. 'capital de 10 000 €' or '50 000 EUR')."""
    match = re.search(
        r'capital[^\d]{0,20}([\d\s\u00a0]+(?:[\.,]\d{1,2})?)\s*(?:€|EUR|euros?)',
        text, re.IGNORECASE
    )
    if match:
        raw = match.group(1).replace('\u00a0', '').replace(' ', '').replace(',', '.')
        return (raw + ' €', MEDIUM)
    return None


def extract_dirigeant(text: str) -> Optional[tuple]:
    """
    Director / gérant name.
    Heuristic: look for 'gérant', 'directeur', 'président', 'CEO' followed by
    a capitalized name (2–4 words).
    """
    match = re.search(
        r'(?:gérant|directeur(?: général)?|président|CEO|dirigeant)\s*:?\s*'
        r'([A-ZÉÈÊÀÂÙÛÔÎ][a-zéèêàâùûôî]+(?:\s+[A-ZÉÈÊÀÂÙÛÔÎ][a-zéèêàâùûôî]+){1,3})',
        text, re.IGNORECASE
    )
    if match:
        return (match.group(1).strip(), LOW)
    return None


def extract_code_postal(text: str) -> Optional[tuple]:
    """French postal code: 5 digits starting with 0–9."""
    match = re.search(r'\b([0-9]{5})\b', text)
    if match:
        return (match.group(1), MEDIUM)
    return None


def extract_ville(text: str) -> Optional[tuple]:
    """
    City name — extracted after the postal code if possible.
    Pattern: 5-digit code followed by a capitalized city name.
    """
    match = re.search(
        r'\b[0-9]{5}\s+([A-ZÉÈÊÀÂÙÛÔÎ][A-ZÉÈÊÀÂÙÛÔÎa-zéèêàâùûôî\-\s]{2,30})\b',
        text
    )
    if match:
        return (match.group(1).strip(), MEDIUM)
    return None


def extract_effectif(text: str) -> Optional[tuple]:
    """
    Employee count / effectif.
    Patterns: '12 salariés', '5 à 9 employés', 'effectif : 50'
    """
    match = re.search(
        r'(?:effectif|salarié[s]?|employé[s]?)\s*[:\-]?\s*(\d+(?:\s*[àa]\s*\d+)?)',
        text, re.IGNORECASE
    )
    if match:
        return (match.group(1).strip(), LOW)
    return None


def extract_linkedin(text: str) -> Optional[tuple]:
    """Extract LinkedIn company page URL."""
    # Exclude ads and share links
    match = re.search(r'(https?://(?:www\.)?linkedin\.com/(?:company|showcase)/[a-zA-Z0-9\-_.]+)', text)
    if match:
        return (match.group(1), MEDIUM)
    return None


def extract_facebook(text: str) -> Optional[tuple]:
    """Extract Facebook company page URL."""
    # Exclude ads, share, and groups if requested. Focus on official page.
    match = re.search(r'(https?://(?:www\.)?facebook\.com/(?!sharer|ads|plugins|tr/)[a-zA-Z0-9\-_.]+)', text)
    if match:
        url = match.group(1)
        if len(url.split("/")) > 3: # Ensure it's not just "facebook.com/"
             return (url, MEDIUM)
    return None


def extract_instagram(text: str) -> Optional[tuple]:
    """Extract Instagram profile URL."""
    match = re.search(r'(https?://(?:www\.)?instagram\.com/(?!p/|stories/|reels/|direct/)[a-zA-Z0-9\-_.]+)', text)
    if match:
        return (match.group(1), MEDIUM)
    return None


def extract_twitter(text: str) -> Optional[tuple]:
    """Extract Twitter/X profile URL."""
    match = re.search(r'(https?://(?:www\.)?(?:twitter\.com|x\.com)/(?!home|intent|share|hashtag/)[a-zA-Z0-9\-_.]+)', text)
    if match:
        return (match.group(1), MEDIUM)
    return None
