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

def verify_phone_neutrino(phone: str) -> Dict[str, Any]:
    """
    Validate a phone number using the Neutrino API.
    
    Args:
        phone: The phone number string to validate.
        
    Returns:
        A dict containing 'valid' (bool) and other metadata.
    """
    if not config.NEUTRINO_ENABLED or not config.NEUTRINO_API_KEY or not config.NEUTRINO_USER_ID:
        logger.debug("[Verifier] Neutrino is disabled or missing credentials.")
        return {"valid": None, "reason": "disabled"}

    # Clean phone for API (remove spaces, etc.)
    clean_phone = "".join(filter(str.isdigit, phone))
    # Ensure it starts with 33 for France if it starts with 0
    if clean_phone.startswith("0") and len(clean_phone) == 10:
        clean_phone = "+33" + clean_phone[1:]
    
    try:
        url = "https://neutrinoapi.net/phone-validate"
        headers = {
            "user-id": config.NEUTRINO_USER_ID,
            "api-key": config.NEUTRINO_API_KEY
        }
        params = {
            "number": clean_phone
        }
        response = requests.get(url, headers=headers, params=params, timeout=10)
        data = response.json()
        
        # Neutrino API error handling
        if response.status_code != 200 or "api-error" in data:
            logger.error(f"[Verifier] Neutrino API error: {data.get('api-error-msg', 'Unknown Error')}")
            return {"valid": None, "reason": "error"}

        if not data.get("valid"):
            logger.warning(f"❌ [Verifier] Neutrino rejected number {phone}")
            return {"valid": False, "carrier": None, "line_type": None}
        
        logger.info(f"✅ [Verifier] Neutrino VALIDATED number {phone} ({data.get('type')})")
        return {
            "valid": True,
            "carrier": None, # Neutrino often doesn't provide carrier in the basic response
            "line_type": data.get("type"), # 'mobile', 'fixed-line', etc.
            "location": data.get("location"),
            "country_name": data.get("country")
        }
    except Exception as e:
        logger.error(f"[Verifier] Neutrino exception: {e}")
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
