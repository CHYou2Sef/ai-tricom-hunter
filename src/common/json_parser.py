"""
╔══════════════════════════════════════════════════════════════════════════╗
║  common/json_parser.py                                                   ║
║                                                                          ║
║  AI Response JSON Extractor                                              ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Extracts and parses JSON objects from raw AI text responses.          ║
║    Handles markdown code blocks, raw strings, and common AI quirks.      ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    1. Searches for ```json ... ``` code blocks first                     ║
║    2. Falls back to finding any { ... } structure                        ║
║    3. Cleans common formatting issues (newlines, trailing commas)        ║
║    4. Recursively strips whitespace from all keys/values                 ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import re
import json
from typing import Optional, Dict, Any
from core.logger import get_logger

logger = get_logger(__name__)

def _deep_strip(data: Any) -> Any:
    """Recursively strip all strings in a dictionary or list, including keys."""
    if isinstance(data, dict):
        return {str(k).strip(' "\''): _deep_strip(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [_deep_strip(i) for i in data]
    elif isinstance(data, str):
        return data.strip()
    return data

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
            data = json.loads(json_str)
            return _deep_strip(data)
        except json.JSONDecodeError as e:
            logger.debug(f"[JSONParser] Raw JSON decode error: {e}")
            # Try a more aggressive cleanup if simple one fails
            try:
                # Remove trailing commas and other common issues
                cleaned = re.sub(r',\s*([\]}])', r'\1', json_str)
                data = json.loads(cleaned)
                return _deep_strip(data)
            except Exception:
                return None
    return None
