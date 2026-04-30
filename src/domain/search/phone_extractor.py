"""
╔══════════════════════════════════════════════════════════════════════════╗
║  domain/search/phone_extractor.py                                        ║
║                                                                          ║
║  Multi-Source Phone Number Extractor & Normalizer                        ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Extracts French phone numbers from both plain text and HTML sources.  ║
║    Normalizes them to a standard "XX XX XX XX XX" format.                ║
║                                                                          ║
║  SOURCES (priority order):                                               ║
║    1. tel: href links    — highest trust (deliberately placed)           ║
║    2. schema.org JSON-LD — structured data                               ║
║    3. data-phone attrs   — semantic markup                               ║
║    4. meta tags          — SEO metadata                                  ║
║    5. Plain text regex   — last resort fallback                          ║
║                                                                          ║
║  FAX AVOIDANCE:                                                          ║
║    Skips numbers near "fax" / "télécopie" keywords to avoid false hits.  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
from typing import List, Optional, Dict, Any
import phonenumbers
from phonenumbers import PhoneNumberFormat
from phonenumbers.phonenumberutil import number_type, PhoneNumberType

from core import config
from core.logger import get_logger

logger = get_logger(__name__)

# ──────────────────────────────────────────────────────────────────────────────
# PATTERNS
# ──────────────────────────────────────────────────────────────────────────────

# Use centralized patterns from config
_TEXT_PATTERNS: List[str] = config.PHONE_PATTERNS

# tel: href pattern  →  <a href="tel:0123456789">
_TEL_HREF_RE   = re.compile(r'href=["\']tel:([+\d\s\.\-]{8,20})["\']', re.IGNORECASE)

# schema.org telephone  →  "telephone": "01 23 45 67 89"
_SCHEMA_RE     = re.compile(r'"telephone"\s*:\s*"([+\d\s\.\-]{8,20})"', re.IGNORECASE)

# meta / data-phone attributes
_DATA_PHONE_RE = re.compile(r'(?:data-phone|data-tel|data-telephone)=["\']([+\d\s\.\-]{8,20})["\']',
                             re.IGNORECASE)

# content="phone:…" or "telephone:…" in meta
_META_RE       = re.compile(r'content=["\'][^\s"\']*?(?:tel|phone|telephone):([+\d\s\.\-]{8,20})["\']',
                             re.IGNORECASE)


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def extract_phones(text: str, source_label: Optional[str] = None) -> List[str]:
    """
    Extract phone numbers from plain text (AI snippets, page text).
    Returns a deduplicated, normalised list.
    """
    if not text:
        return []
    return _dedupe_and_log(_find_in_text(text), source_label)


def extract_phones_from_html(html: str, source_label: Optional[str] = None) -> List[str]:
    """
    Extract phone numbers from raw HTML page source.
    Scans in priority order:
      1. <a href="tel:…"> links
      2. schema.org JSON-LD "telephone"
      3. data-phone / data-tel attributes
      4. Regex over ALL visible text content in the HTML
    Returns a deduplicated, normalised list.
    """
    if not html:
        return []

    found: List[str] = []

    # ── Priority 1: tel: href links (most authoritative) ──
    found.extend(_match_and_normalize(_TEL_HREF_RE, html))

    # ── Priority 2: schema.org telephone ──
    found.extend(_match_and_normalize(_SCHEMA_RE, html))

    # ── Priority 3: data-phone / data-tel attributes ──
    found.extend(_match_and_normalize(_DATA_PHONE_RE, html))

    # ── Priority 4: meta content ──
    found.extend(_match_and_normalize(_META_RE, html))

    # ── Priority 5: plain-text regex over the whole HTML ──
    # Strip tags first so we don't catch partial hex codes inside style/script
    clean_text = re.sub(r'<[^>]+>', ' ', html)
    found.extend(_find_in_text(clean_text))

    return _dedupe_and_log(found, source_label)


def get_best_phone(phones: List[str]) -> Optional[str]:
    """
    Return the single best phone from a list:
      1. Prefers mobile (06/07)
      2. Falls back to the first found
    """
    if not phones:
        return None

    for p in phones:
        clean = p.replace(' ', '').replace('.', '').replace('-', '')
        if clean.startswith('06') or clean.startswith('07'):
            return p

    return phones[0]


# ──────────────────────────────────────────────────────────────────────────────
# PRIVATE HELPERS
# ──────────────────────────────────────────────────────────────────────────────

def _find_in_text(text: str) -> List[str]:
    """Apply all plain-text patterns to `text` and filter out likely fax numbers."""
    found = []
    
    # ── Fax avoidance context window ──
    fax_keywords = ['fax', 'télécopie', 'telecopie', 'télécopieur']
    
    for pattern in _TEXT_PATTERNS:
        # Use finditer to know where the match occurred in the string
        for m in re.finditer(pattern, text):
            raw_match = m.group(0)
            start, end = m.span()
            
            # Extract +/- 30 characters surrounding the match
            context_start = max(0, start - 30)
            context_end = min(len(text), end + 30)
            context = text[context_start:context_end].lower()
            
            # If a fax keyword is found near the number, skip it
            is_fax = any(k in context for k in fax_keywords)
            if is_fax:
                logger.debug(f"[PhoneExtractor] Skipped likely FAX number: {raw_match}")
                continue
                
            n = normalize_phone(raw_match)
            if n:
                found.append(n)
    return found


def _match_and_normalize(pattern: re.Pattern, text: str) -> List[str]:
    """Apply a compiled pattern and normalize each captured group."""
    results = []
    for m in pattern.findall(text):
        n = normalize_phone(m)
        if n:
            results.append(n)
    return results


def _dedupe_and_log(phones: List[str], source_label: Optional[str] = None) -> List[str]:
    """Deduplicate while preserving priority order, then log."""
    seen = set()
    unique = []
    for p in phones:
        if p not in seen:
            seen.add(p)
            unique.append(p)
    
    if unique:
        label = f" ({source_label})" if source_label else ""
        logger.info(f"✨ [PhoneExtractor] Found {len(unique)} phone(s){label}: {unique}")
    else:
        logger.debug("[PhoneExtractor] No phone numbers found.")
    return unique


def is_valid_french_phone(digits: str) -> bool:
    """
    Structural anti-hallucination validator. Uses blocklist and structural checks
    before passing to the deep phonenumbers validation.
    """
    # 1. Hard blocklist (exact matches)
    if digits in config.FAKE_PHONE_BLOCKLIST:
        logger.debug(f"[PhoneExtractor] Blocked (blocklist): {digits}")
        return False

    # 2. All same digit: '0000000000', '0666666666', etc.
    if len(set(digits)) == 1:
        logger.debug(f"[PhoneExtractor] Blocked (all-same-digit): {digits}")
        return False

    # 3. Monotonically sequential digits (e.g. 0123456789)
    if digits == ''.join(str(i % 10) for i in range(len(digits))):
        logger.debug(f"[PhoneExtractor] Blocked (sequential ascending): {digits}")
        return False

    return True

def get_phone_metadata(phone_str: str) -> Dict[str, Any]:
    """Returns metadata for a valid phone number, including line type."""
    meta = {"type": "UNKNOWN"}
    if not phone_str:
        return meta
    try:
        num = phonenumbers.parse(phone_str, "FR")
        ptype = number_type(num)
        if ptype == PhoneNumberType.MOBILE:
            meta["type"] = "MOBILE"
        elif ptype == PhoneNumberType.FIXED_LINE:
            meta["type"] = "FIXED_LINE"
        elif ptype == PhoneNumberType.FIXED_LINE_OR_MOBILE:
            meta["type"] = "FIXED_LINE_OR_MOBILE"
        elif ptype == PhoneNumberType.TOLL_FREE:
            meta["type"] = "TOLL_FREE"
        elif ptype == PhoneNumberType.PREMIUM_RATE:
            meta["type"] = "PREMIUM_RATE"
        elif ptype == PhoneNumberType.VOIP:
            meta["type"] = "VOIP"
    except Exception:
        pass
    return meta

def normalize_phone(phone: Optional[str]) -> Optional[str]:
    """
    Normalise a raw phone string using `phonenumbers`:
      - Reject fake/hallucinated numbers via blocklist + structural checks
      - Validate structurally and syntactically using libphonenumber
      - Format French numbers as 'XX XX XX XX XX'
    """
    if not phone:
        return None

    digits_only = re.sub(r'[\s\.\-\(\)]', '', str(phone)).strip()
    
    # Quick sanity checks to avoid parsing junk
    if len(digits_only) < 9 or len(digits_only) > 15:
        return None
        
    # Convert +33XXXXXXXXX to 0XXXXXXXXX for our blocklist checks
    fr_digits = digits_only
    if fr_digits.startswith('+33') and len(fr_digits) == 12:
        fr_digits = '0' + fr_digits[3:]

    # Apply hallucination rules (Blocklist + sequential checks)
    if fr_digits.startswith('0') and len(fr_digits) == 10:
        if not is_valid_french_phone(fr_digits):
            return None

    try:
        # Use phonenumbers to parse (defaults to France if no + code)
        num = phonenumbers.parse(phone, "FR")
        
        if not phonenumbers.is_valid_number(num):
            logger.debug(f"[PhoneExtractor] Blocked (phonenumbers invalid): {phone}")
            return None
            
        # Format uniformly (NATIONAL for FR numbers -> 0X XX XX XX XX)
        if num.country_code == 33:
            return phonenumbers.format_number(num, PhoneNumberFormat.NATIONAL)
        else:
            return phonenumbers.format_number(num, PhoneNumberFormat.INTERNATIONAL)
            
    except phonenumbers.NumberParseException:
        return None
