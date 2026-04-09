"""
utils/universal_extractor.py

Universal Unified Extractor (UUE)
This module acts as the central brain for all 4 browser tiers. 
Instead of browsers attempting to parse data via Javascript or CSS locators dynamically 
(which often fails and triggers false alerts), the browsers simply pass the full HTML DOM 
string here.

Features:
1. Semantic Layer: Extracts JSON-LD Schema.org data.
2. Heuristic Layer: Extracts hidden Google Knowledge Graph attributes.
3. Visual Layer: Extracts explicit 'tel:' and 'mailto:' href links.
"""

import json
import re
from typing import Dict, Any, List
from bs4 import BeautifulSoup

from utils.logger import get_logger
logger = get_logger(__name__)

class UniversalExtractor:
    
    @classmethod
    def extract_all(cls, html_source: str) -> Dict[str, Any]:
        """
        Main entry point for UUE.
        Returns a dictionary containing matched data points.
        """
        result = {
            "aeo_data": [],
            "heuristic_phones": [],
            "heuristic_emails": [],
            "semantic_phones": []
        }
        
        if not html_source or not isinstance(html_source, str):
            return result
            
        try:
            soup = BeautifulSoup(html_source, 'html.parser')
            
            # --- 1. Semantic Layer (JSON-LD) ---
            scripts = soup.find_all("script", type="application/ld+json")
            for script in scripts:
                if script.string:
                    try:
                        data = json.loads(script.string.strip())
                        if isinstance(data, dict):
                            result["aeo_data"].append(data)
                        elif isinstance(data, list):
                            result["aeo_data"].extend(data)
                    except Exception:
                        pass
                        
            # --- 2. Heuristic Layer (Google Knowledge Panel & Local Pack locators) ---
            kg_phone_selectors = [
                 "[data-dtype='d3ph'] span", 
                 "a[data-dtype='d3ph']", 
                 "[data-attrid='kc:/local:phone'] span",
                 "[data-attrid='tel'] span"
            ]
            for selector in kg_phone_selectors:
                elements = soup.select(selector)
                for el in elements:
                    text_content = el.get_text(strip=True)
                    if text_content and len(text_content) > 5:
                         result["heuristic_phones"].append(text_content)
                         
                    # Check aria-label
                    aria = el.get("aria-label")
                    if aria and "Call phone number" in aria:
                        phone = aria.replace("Call phone number", "").strip()
                        if phone:
                             result["heuristic_phones"].append(phone)
            
            # Generic aria-label search in the whole DOM
            for el in soup.select("[aria-label*='Call phone number']"):
                 aria = el.get("aria-label")
                 if aria:
                      phone = aria.replace("Call phone number", "").strip()
                      if phone and len(phone) > 5:
                           result["heuristic_phones"].append(phone)

            # --- 3. Visual Layer (HREFs) ---
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip().lower()
                if href.startswith("tel:"):
                    result["heuristic_phones"].append(href[4:])
                elif href.startswith("mailto:"):
                    result["heuristic_emails"].append(href[7:])
                    
            # --- Deduplicate ---
            result["heuristic_phones"] = list(set([p for p in result["heuristic_phones"] if p]))
            result["heuristic_emails"] = list(set([e for e in result["heuristic_emails"] if e]))
            
            # Logging if something was found
            found_aeo = len(result["aeo_data"])
            found_phones = len(result["heuristic_phones"])
            logger.info(f"🧠 [UniversalExtractor] Analyzing DOM... Found {found_aeo} JSON-LD blocks & {found_phones} heuristic phones.")
                
        except Exception as e:
            logger.error(f"[UUE] Parsing error: {e}")
            
        return result
