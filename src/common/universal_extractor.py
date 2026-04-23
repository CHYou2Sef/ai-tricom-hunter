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

from core.logger import get_logger
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
                 "[data-dtype='d3ph'] span", "a[data-dtype='d3ph']", 
                 "[data-attrid='kc:/local:phone'] span", "[data-attrid='tel'] span",
                 ".LGOjhe span", ".zS8pY", "span[data-dtype='d3ph']",
                 ".kno-rdesc span", ".yDYNvb.lyLwlc",
                 "div[data-attrid='wa:/description'] span", "[data-chunk-index='0']",
                 ".wDYxhc .VwiC3b", ".rllt__details", ".vlist"
            ]
            for selector in kg_phone_selectors:
                for el in soup.select(selector):
                    txt = el.get_text(" ", strip=True).replace("Téléphone :", "").replace("Appeler", "").strip()
                    if txt and len(txt) > 5: result["heuristic_phones"].append(txt)
            
            # Generic aria-label search in the whole DOM
            for el in soup.select("[aria-label*='phone'], [aria-label*='téléphone'], [aria-label*='Call']"):
                 aria = el.get("aria-label")
                 if aria:
                      match = re.search(r"(\+?\d[\d\s\.\-]{8,}\d)", aria)
                      if match: result["heuristic_phones"].append(match.group(1))

            # --- 3. Visual Layer (HREFs) ---
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip().lower()
                if href.startswith("tel:"):
                    result["heuristic_phones"].append(href[4:])
                elif href.startswith("mailto:"):
                    result["heuristic_emails"].append(href[7:])
            
            # --- 4. Global Regex Fallback (Last resort within UUE) ---
            # If we found nothing semantic or heuristic, scan the raw text 
            # so we don't return an "Empty" result if data is visible.
            if not result["heuristic_phones"]:
                from domain.search.phone_extractor import extract_phones  # noqa: PLC0415
                raw_text = soup.get_text(" ", strip=True)
                regex_phones = extract_phones(raw_text)
                if regex_phones:
                    result["heuristic_phones"] = regex_phones[:5] # Take top 5
                    
            # --- 5. Social & Discovery Layer ---
            result["social_links"] = {
                "facebook": [],
                "linkedin": [],
                "instagram": [],
                "website": []
            }
            
            # Identify potential official website and social profiles
            for a_tag in soup.find_all("a", href=True):
                href = a_tag["href"].strip()
                href_lower = href.lower()
                
                # Social detection
                if "facebook.com" in href_lower and "/sharer" not in href_lower:
                    result["social_links"]["facebook"].append(href)
                elif "linkedin.com/company" in href_lower:
                    result["social_links"]["linkedin"].append(href)
                elif "instagram.com" in href_lower:
                    result["social_links"]["instagram"].append(href)
                
                # Official Website detection (heuristics from top results)
                # Look for links in search results that don't belong to known directories
                KNOWN_DIRECTORIES = ["societe.com", "pappers.fr", "pagesjaunes.fr", "infogreffe.fr", "verif.com", "manageo.fr"]
                if href.startswith("http") and not any(dir in href_lower for dir in KNOWN_DIRECTORIES + ["google.com", "facebook.com", "linkedin.com", "instagram.com", "twitter.com"]):
                    result["social_links"]["website"].append(href)

            # Deduplicate social links
            for k in result["social_links"]:
                result["social_links"][k] = list(set(result["social_links"][k]))
                    
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
