import re
import json
from typing import Optional, Dict, Any
from utils.logger import get_logger

logger = get_logger(__name__)

def parse_ai_mode_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Extracts and parses a JSON object from a raw AI search response text.
    Handles markdown blocks and raw strings.
    """
    if not text:
        return None

    # Try to find JSON inside a code block ```json ... ```
    json_match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL | re.IGNORECASE)
    if not json_match:
        # Try to find any JSON-like structure { ... }
        json_match = re.search(r'(\{.*\})', text, re.DOTALL)

    if json_match:
        try:
            json_str = json_match.group(1).strip()
            # Basic cleanup for common AI formatting quirks
            json_str = json_str.replace('\n', ' ').replace('\r', '')
            return json.loads(json_str)
        except json.JSONDecodeError as e:
            logger.debug(f"[JSONParser] Raw JSON decode error: {e}")
            # Try a more aggressive cleanup if simple one fails
            try:
                # Remove trailing commas and other common issues
                cleaned = re.sub(r',\s*([\]}])', r'\1', json_str)
                return json.loads(cleaned)
            except Exception:
                return None
    return None
