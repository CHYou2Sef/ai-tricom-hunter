"""
╔══════════════════════════════════════════════════════════════════════════╗
║  agents/phone_hunter.py                                                  ║
║                                                                          ║
║  Role: Primary phone extraction orchestrator for each Excel row.         ║
║  Uses a multi-tier waterfall: AI Mode → Knowledge Panel → Web Scraping.  ║
║  Falls back to local LLM (Ollama) if cloud extraction fails.             ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import time
import logging
import re
import json
import asyncio
from typing import Optional, Tuple, List, Dict, Any

from core import config
from domain.excel.reader import ExcelRow
from core.logger import get_logger
from common.text_cleaner import clean_html_to_text
from domain.search.phone_extractor import extract_phones, get_best_phone, normalize_phone
from common.json_parser import parse_ai_mode_json
from infra.intelligence.ollama_client import ollama_client

logger = get_logger(__name__)

from common.search_engine import build_b2b_query

def build_search_query(row: ExcelRow) -> str:
    """Build a B2B search query from row name + address."""
    nom = row.get_search_name()   # company name or SIREN fallback
    adr = row.adresse or ""       # physical address for geo disambiguation
    return build_b2b_query(nom, adr)

def build_agent_query(row: ExcelRow) -> str:
    """Build a targeted agent-phone prompt (director/mobile lines)."""
    nom     = row.get_search_name()
    adresse = row.adresse or ""
    return config.AGENT_PHONE_PROMPT_TEMPLATE.format(nom=nom, adresse=adresse)

async def _search_knowledge_panel_phone(row: ExcelRow, agent, query: str) -> Optional[str]:
    """
    Try Google's Knowledge Panel for a direct phone hit.
    Knowledge Panels appear for well-known businesses and often list
    phones, emails, and URLs without needing page scraping.

    Args:
        row   : ExcelRow being processed (mutated for provenance tracking)
        agent : Active browser agent (HybridAutomationEngine)
        query : Pre-built search string (company + address)

    Returns:
        Normalised phone string or None if panel is absent/empty.
    """
    row.search_queries_used.append(f"KP: {query}")
    logger.info(f"    ├─ [UUE] Knowledge Panel Search: '{query}'")

    success = await agent.submit_google_search(query)
    if not success:
        return None

    await asyncio.sleep(2)   # Let JS-rendered panel stabilise
    
    metadata = await agent.extract_universal_data() or {}
    best_phone = None
    
    # Phones are ranked by confidence by the underlying extractor
    if metadata.get("heuristic_phones"):
        best_phone = metadata["heuristic_phones"][0]
                
    if best_phone:
        normalized = normalize_phone(best_phone)
        if normalized:
            row.raw_ai_responses.append({
                "text":   f"UUE Heuristic Phone Found: {normalized}",
                "source": "google_kp",
                "query":  query,
            })
            # Opportunistically grab email / website from the same panel
            for block in metadata.get("aeo_data", []):
                for field, key in [("email", "email"), ("website", "url")]:
                    val = block.get(key)
                    if val and field not in row.enriched_fields:
                        if isinstance(val, list): val = val[0]
                        row.enriched_fields[field] = {"value": val, "source": "JSON-LD"}
            
            logger.info(f"✨ [UUE] Method SUCCESS: {normalized}")
            return normalized
    return None

async def _extract_geo_phone(row: ExcelRow, agent, page_content: str) -> Optional[str]:
    """
    GEO (Generative Engine Optimisation) fallback via local Ollama LLM.
    Converts raw HTML into a structured prompt and asks the model to
    extract the phone number.  Used only when cloud APIs return nothing.

    Args:
        row         : ExcelRow (for name/address context)
        agent       : Browser agent (unused but kept for signature consistency)
        page_content: Raw HTML from the last visited page

    Returns:
        Phone string parsed from model JSON or None.
    """
    if not config.OLLAMA_ENABLED:
        return None   # Local LLM disabled in .env — skip to save time
    logger.info(f"    [GEO] Initializing Local LLM (Ollama) fallback...")
    # Clamp context to 8k chars to fit small models (3B params) and avoid OOM
    context = clean_html_to_text(page_content)[:8000].strip()
    geo_prompt = config.GEO_FALLBACK_PROMPT.format(
        nom=row.nom or row.siren,
        adresse=row.adresse,
        raw_web_context=context
    )
    geo_response = await ollama_client.complete(geo_prompt)
    if geo_response:
        row.raw_ai_responses.append({"text": geo_response, "source": "ollama_local", "query": geo_prompt[:200]})
        try:
            # Ollama may emit markdown → strip everything outside the JSON block
            json_match = re.search(r'\{.*\}', geo_response, re.DOTALL)
            if json_match:
                res = json.loads(json_match.group(0).strip())
                tel = res.get("telephone")
                if tel and str(tel).upper() not in ("NOT_FOUND", "NONE", ""):
                    return tel
        except Exception:   # Malformed JSON or unexpected format — safe to ignore
            pass
    return None

async def _search_and_extract_phone(row: ExcelRow, agent, query: str, source_tag: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Generic search → extract pipeline.  Tries UA metadata first,
    then regex extraction, then GEO/Ollama fallback.

    Args:
        row        : ExcelRow (logs query provenance)
        agent      : Active browser agent
        query      : Search string
        source_tag : Provenance label (e.g. "google_scrap") used for scoring

    Returns:
        (phone_or_None, full_page_text_or_None)
    """
    row.search_queries_used.append(query)
    logger.info(f"    ├─ [{source_tag.upper()}] Query: '{query}'")
    content = await agent.search_google_ai(query)
    if content:
        row.raw_ai_responses.append({"text": content, "source": source_tag, "query": query})
    
    # 1. Structured metadata (highest confidence — often from Knowledge Panel)
    metadata = await agent.extract_universal_data() or {}
    phone = metadata.get("heuristic_phones")[0] if metadata.get("heuristic_phones") else None
    
    # 2. Regex heuristics on raw text
    if not phone and content:
        phones = extract_phones(content, source_label=source_tag)
        phone = get_best_phone(phones)
    # 3. Local LLM last resort
    if not phone and content:
        phone = await _extract_geo_phone(row, agent, content)
    return phone, content

def _fill_row_from_ai_mode(raw_text: str, row: ExcelRow) -> Optional[str]:
    """
    Parse the JSON blob returned by Google AI Mode and populate
    the ExcelRow with as many structured fields as possible.

    Args:
        raw_text : Unstructured text from AI Mode (may contain markdown)
        row      : ExcelRow to mutate with enriched data

    Returns:
        The best phone found, or None.
    """
    data = parse_ai_mode_json(raw_text)
    if not data: return None
    phones_raw = data.get("phone_numbers") or data.get("telephone") or data.get("phone")
    best = None
    if isinstance(phones_raw, list) and phones_raw:
        best = normalize_phone(phones_raw[0])
    elif isinstance(phones_raw, str):
        best = normalize_phone(phones_raw)
    if not best:
        # Fallback: regex on the raw text if JSON key was missing
        candidates = extract_phones(raw_text, source_label="google_ai_mode")
        best = get_best_phone(candidates)
    
    # Mapping: output key → list of possible JSON keys (handles model inconsistency)
    field_map = {
        "email": ["email"], "linkedin": ["linkedin", "linkedin_url"],
        "website": ["website", "website_url"], "siren": ["siren"],
        "siret": ["siret"], "legal_form": ["legal_form", "legal_name", "forme_juridique"],
        "naf": ["activity_code_naf", "naf"], "address": ["headquarters_address", "address"],
        "dirigeant": ["director", "dirigeant", "ceo", "responsable_person", "responsable"], "capital": ["capital"],
        "ville": ["city", "ville"], "code_postal": ["postal_code", "code_postal"],
        "facebook": ["facebook", "facebook_url"], "instagram": ["instagram", "instagram_url"],
        "direct_phone": ["director_direct_phone", "tel_direct", "mobile"],
    }
    # Maps enriched field names back to ExcelRow attribute names
    attr_map = {
        "email": "email", "linkedin": "linkedin", "website": "website", "siren": "siren",
        "siret": "siret", "legal_form": "forme_juridique", "naf": "naf",
        "dirigeant": "dirigeant", "capital": "capital", "ville": "ville", "code_postal": "code_postal",
        "facebook": "facebook", "instagram": "instagram", "direct_phone": "phone_agent"
    }
    for row_key, json_keys in field_map.items():
        for jk in json_keys:
            val = data.get(jk)
            if isinstance(val, dict): val = ", ".join(str(v) for v in val.values() if v)
            elif isinstance(val, list): val = ", ".join(str(v) for v in val if v)
            if val and str(val).upper() not in ("NOT_FOUND", "NONE", "", "NULL"):
                clean_val = str(val).strip()
                row.enriched_fields[row_key] = {"value": clean_val, "source": "google_ai_mode", "confidence": 0.97}
                attr = attr_map.get(row_key)
                if attr and not getattr(row, attr, None): setattr(row, attr, clean_val)
                break
    
    # --- Consistency Validation: SIREN cross-check to detect hallucination ---
    extracted_siren = data.get("siren")
    if extracted_siren and row.siren:
        clean_ext = "".join(filter(str.isdigit, str(extracted_siren)))
        clean_row = "".join(filter(str.isdigit, str(row.siren)))
        if clean_ext != clean_row:
            logger.warning(f"🚩 [Validation] SIREN Mismatch! Expected {clean_row}, got {clean_ext}. High risk of hallucination.")
            row.enriched_fields["validation_error"] = "SIREN_MISMATCH"
            
    return best

def _calculate_row_confidence(row: ExcelRow) -> int:
    """
    Compute a composite confidence score (0-100) for the row.
    Factors: extraction source quality, SIREN validation penalty.

    Args:
        row : ExcelRow containing harvested phones and validation state

    Returns:
        Integer confidence percentage.
    """
    if not row.phone: return 0
    
    phone_list = row.enriched_fields.get("phone_list", [])
    if not phone_list: return 50   # Default mid-confidence when no metadata
    
    best_score = max(h.get('score', 0) for h in phone_list)
    
    # Penalise hallucination risk when SIREN extracted ≠ SIREN input
    if row.enriched_fields.get("validation_error") == "SIREN_MISMATCH":
        best_score -= 30
        
    return max(0, best_score)

async def process_row(row: ExcelRow, agent, idx: Optional[int] = None, total: Optional[int] = None) -> List[dict]:
    """
    Harvests phones and stores them with confidence scores in enriched_fields.
    Returns a list of dicts: {'num': ..., 'score': ..., 'source': ...}
    """
    if row.status == "DONE" and not config.REPROCESS_FAILED_ROWS:
        logger.info(f"[Agent] Row #{row.row_index} SKIPPED — status={row.status}.")
        return []

    progress_str = f"{idx}/{total}" if idx and total else f"#{row.row_index}"
    siren_log = row.siren if row.siren else ""
    
    # Set current row for telemetry
    if hasattr(agent, 'current_row_index'):
        agent.current_row_index = row.row_index
        
    logger.info(f"🔍 [Verification] Row {progress_str} | Target: '{row.nom}' | SIREN: {siren_log} | Localité: '{row.adresse}'")
    
    row.processing_start_ts = time.perf_counter()
    harvested = [] # List of {'num', 'score', 'source'}

    def add_unique(num, score, source):
        norm = normalize_phone(num)
        if not norm: return
        # Avoid duplication with original file data
        if row.phone and normalize_phone(row.phone) == norm: return
        # Avoid duplicate numbers in same session
        if any(h['num'] == norm for h in harvested): return
        harvested.append({"num": norm, "score": score, "source": source})

    # ── 1. Target Identification ──────────────────────────────────────────
    # Priority: Raison Sociale > Enseigne > SIREN identifier
    nom_base = row.nom or "Entreprise"
    if not row.nom and row.siren:
        nom = f"Entreprise (SIREN {row.siren})"
    else:
        nom = row.nom or row.siren or "Inconnue"
        
    adr = row.adresse or "France"
    siren = row.siren or ""
    category = row.category or ""
    extra = row.raw_context[:200]
    
    # Existing phones to avoid duplication
    existing = set()
    if row.phone: existing.add(normalize_phone(row.phone))

    # 1. AI Mode Searches (High Confidence)
    # Waterfall: Try Standard -> if fail -> Try Expert
    last_meta = None
    for prompt_key, tag in [(config.AI_MODE_SEARCH_PROMPT, "ai_std"), (config.AI_MODE_EXPERT_PROMPT, "ai_expert")]:
        if any(h['score'] >= 90 for h in harvested): break
            
        prompt = prompt_key.format(nom=nom, adresse=adr, siren=siren, category=category, extra=extra)
        ai_raw = await agent.search_google_ai_mode(prompt)
        last_meta = getattr(agent, "last_metadata", None)
        
        if ai_raw:
            row.raw_ai_responses.append({"text": ai_raw, "source": tag, "query": prompt[:100]})
            candidates = extract_phones(ai_raw, source_label=tag)
            for p in candidates: add_unique(p, 97, tag)
            _fill_row_from_ai_mode(ai_raw, row)

    # 1.5 DEEP DISCOVERY (Official Site & Social Media "About")
    if not any(h['score'] >= 90 for h in harvested) and last_meta:
        discovery_links = last_meta.get("social_links", {})
        # Target: Top Website + Facebook About + LinkedIn About
        targets = []
        if discovery_links.get("website"): targets.append((discovery_links["website"][0], "discovery_web"))
        if discovery_links.get("facebook"): targets.append((discovery_links["facebook"][0].rstrip("/") + "/about", "discovery_fb"))
        if discovery_links.get("linkedin"): targets.append((discovery_links["linkedin"][0].rstrip("/") + "/about/", "discovery_li"))
        
        for url, source_tag in targets[:3]: # Cap at 3 discovery visits
            if any(h['score'] >= 90 for h in harvested): break
            logger.info(f"🔎 [DeepDiscovery] Opening: {url}")
            if await agent.goto_url(url):
                source = await agent.get_page_source()
                if source:
                    row.raw_ai_responses.append({"text": source[:10000], "source": source_tag, "url": url})
                
                page_meta = await agent.extract_universal_data()
                if page_meta and page_meta.get("heuristic_phones"):
                    for p in page_meta["heuristic_phones"]:
                        add_unique(p, 95 if "fb" in source_tag or "li" in source_tag else 90, source_tag)

    # 2. Knowledge Panel (Highest Confidence)
    if not any(h['score'] >= 90 for h in harvested) and row.nom:
        kp_phone = await _search_knowledge_panel_phone(row, agent, f"{row.nom} {adr}")
        if kp_phone:
            add_unique(kp_phone, 99, "google_kp")

    # 3. Web Scraping (Medium Confidence)
    if not any(h['score'] >= 90 for h in harvested):
        q = build_search_query(row)
        if q:
            res, content = await _search_and_extract_phone(row, agent, q, "google_scrap")
            if content:
                candidates = extract_phones(content, source_label="web_scrap")
                for p in candidates:
                    add_unique(p, 85, "web_scrap")

    # 4. Final results mapping
    row.processing_end_ts = time.perf_counter()
    elapsed = round(row.processing_end_ts - row.processing_start_ts, 1)
    
    if harvested:
        # Sort by score descending
        harvested.sort(key=lambda x: x['score'], reverse=True)
        row.phone = harvested[0]['num'] # Main phone
        
        # Binary Status: If we have a phone, it's DONE. No more 'LOW_CONF'.
        final_conf = _calculate_row_confidence(row)
        row.status = "DONE"
        
        # Store full list in enriched_fields for column expansion
        row.enriched_fields["phone_list"] = harvested
        row.enriched_fields["final_confidence"] = final_conf
        
        # Save Tier Provenance
        if hasattr(agent, 'last_successful_tier_used'):
            row.enriched_fields["tier"] = agent.last_successful_tier_used
        
        logger.info(f"🏆 [Row {progress_str}] Status: {row.status} (Conf: {final_conf}%) | Best: {row.phone} | Time: {elapsed}s")
    else:
        row.status = "NO TEL"
        logger.warning(f"🔦 [Row {progress_str}] DEPLETED: No phone found | Time: {elapsed}s")

    return harvested
