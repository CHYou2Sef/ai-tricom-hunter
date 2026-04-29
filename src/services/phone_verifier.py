"""
╔══════════════════════════════════════════════════════════════════════════╗
║  services/phone_verifier.py                                              ║
║                                                                          ║
║  Role: Deterministic phone validation via external APIs (Numverify).      ║
║  Used to break ties or confirm LOW_CONF (SIREN mismatch) numbers.        ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import requests
from typing import Optional, Dict, Any
from core import config
from core.logger import get_logger

logger = get_logger(__name__)

def verify_phone_numverify(phone: str) -> Dict[str, Any]:
    """
    Validate a phone number using the Numverify API.
    
    Args:
        phone: The phone number string to validate.
        
    Returns:
        A dict containing 'valid' (bool) and other metadata.
    """
    if not config.NUMVERIFY_ENABLED or not config.NUMVERIFY_API_KEY:
        logger.debug("[Verifier] Numverify is disabled or missing API key.")
        return {"valid": None, "reason": "disabled"}

    # Clean phone for API (remove spaces, etc.)
    clean_phone = "".join(filter(str.isdigit, phone))
    # Ensure it starts with 33 for France if it starts with 0
    if clean_phone.startswith("0") and len(clean_phone) == 10:
        clean_phone = "33" + clean_phone[1:]
    
    try:
        url = f"http://apilayer.net/api/validate?access_key={config.NUMVERIFY_API_KEY}&number={clean_phone}"
        response = requests.get(url, timeout=10)
        data = response.json()
        
        if not data.get("valid"):
            logger.warning(f"❌ [Verifier] Numverify rejected number {phone}: {data.get('error', 'Invalid')}")
            return {"valid": False, "carrier": data.get("carrier"), "line_type": data.get("line_type")}
        
        logger.info(f"✅ [Verifier] Numverify VALIDATED number {phone} ({data.get('line_type')})")
        return {
            "valid": True,
            "carrier": data.get("carrier"),
            "line_type": data.get("line_type"),
            "location": data.get("location"),
            "country_name": data.get("country_name")
        }
    except Exception as e:
        logger.error(f"[Verifier] Numverify API error: {e}")
        return {"valid": None, "reason": "error"}

def verify_phone_consensus(phone: str, harvested_list: list) -> bool:
    """
    Fallback consensus verification: is this number found by multiple sources?
    """
    if not harvested_list:
        return False
    
    # Count occurrences of this specific number
    count = sum(1 for h in harvested_list if h.get("num") == phone)
    
    # If found by 2+ distinct sources, we have higher confidence
    if count >= 2:
        logger.info(f"🤝 [Verifier] Consensus validation SUCCESS for {phone} ({count} sources)")
        return True
    
    return False
