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

def build_search_query(row: ExcelRow) -> str:
    if row.nom:
        keywords = config.SQO_CONTACT_KEYWORDS
        trusted  = config.SQO_TRUSTED_DOMAINS
        return f'"{row.nom}" "{row.adresse or ""}" {keywords} {trusted}'
    elif row.siren:
        return config.SIREN_SEARCH_TEMPLATE.format(siren=row.siren)
    return ""

def build_agent_query(row: ExcelRow) -> str:
    nom     = row.get_search_name()
    adresse = row.adresse or ""
    return config.AGENT_PHONE_PROMPT_TEMPLATE.format(nom=nom, adresse=adresse)

async def _search_knowledge_panel_phone(row: ExcelRow, agent, query: str) -> Optional[str]:
    row.search_queries_used.append(f"KP: {query}")
    logger.info(f"    ├─ [Tier 0] Knowledge Panel Search: '{query}'")

    success = await agent.submit_google_search(query)
    if not success:
        return None

    await asyncio.sleep(3)
    
    metadata = await agent.extract_universal_data() or {}
    best_phone = None
    
    if metadata.get("heuristic_phones"):
        best_phone = metadata["heuristic_phones"][0]
    elif metadata.get("aeo_data"):
        for block in metadata["aeo_data"]:
            tel = block.get("telephone") or block.get("contactPoint", {}).get("telephone")
            if tel:
                best_phone = tel
                break
                
    if best_phone:
        normalized = normalize_phone(best_phone)
        if normalized:
            row.raw_ai_responses.append({
                "text":   f"Knowledge Panel/UUE Phone Found: {normalized}",
                "source": "google_kp",
                "query":  query,
            })
            for block in metadata.get("aeo_data", []):
                email = block.get("email")
                if email and "email" not in row.enriched_fields:
                    row.enriched_fields["email"] = {"value": email, "source": "JSON-LD"}
                
                url = block.get("url") or block.get("sameAs")
                if url:
                    if isinstance(url, list): url = url[0]
                    if "website" not in row.enriched_fields:
                        row.enriched_fields["website"] = {"value": url, "source": "JSON-LD"}
            
            if metadata.get("heuristic_emails") and "email" not in row.enriched_fields:
                row.enriched_fields["email"] = {"value": metadata["heuristic_emails"][0], "source": "UUE-Visual"}

            logger.info(f"✨ [Tier 0/UUE] Method SUCCESS: {normalized}")
            return normalized
    return None

async def _extract_geo_phone(row: ExcelRow, agent, page_content: str) -> Optional[str]:
    if not config.OLLAMA_ENABLED:
        return None
    logger.info(f"    [GEO] Initializing Local LLM (Ollama) fallback...")
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
            json_match = re.search(r'\{.*\}', geo_response, re.DOTALL)
            if json_match:
                res = json.loads(json_match.group(0).strip())
                tel = res.get("telephone")
                if tel and str(tel).upper() not in ("NOT_FOUND", "NONE", ""):
                    return tel
        except: pass
    return None

async def _search_and_extract_phone(row: ExcelRow, agent, query: str, source_tag: str) -> Tuple[Optional[str], Optional[str]]:
    row.search_queries_used.append(query)
    logger.info(f"    ├─ [{source_tag.upper()}] Query: '{query}'")
    content = await agent.search_google_ai(query)
    if content:
        row.raw_ai_responses.append({"text": content, "source": source_tag, "query": query})
    
    metadata = await agent.extract_universal_data() or {}
    phone = None
    for block in metadata.get("aeo_data", []):
        tel = block.get("telephone") or block.get("contactPoint", {}).get("telephone")
        if tel:
            phone = tel
            break
    if not phone and metadata.get("heuristic_phones"):
        phone = metadata["heuristic_phones"][0]
    if not phone and content:
        phones = extract_phones(content, source_label=source_tag)
        phone = get_best_phone(phones)
    if not phone and content:
        phone = await _extract_geo_phone(row, agent, content)
    return phone, content

def _fill_row_from_ai_mode(raw_text: str, row: ExcelRow) -> Optional[str]:
    data = parse_ai_mode_json(raw_text)
    if not data: return None
    phones_raw = data.get("phone_numbers") or data.get("telephone") or data.get("phone")
    best = None
    if isinstance(phones_raw, list) and phones_raw:
        best = normalize_phone(phones_raw[0])
    elif isinstance(phones_raw, str):
        best = normalize_phone(phones_raw)
    if not best:
        candidates = extract_phones(raw_text, source_label="google_ai_mode")
        best = get_best_phone(candidates)
    
    field_map = {
        "email": ["email"], "linkedin": ["linkedin", "linkedin_url"],
        "website": ["website", "website_url"], "siren": ["siren"],
        "siret": ["siret"], "legal_form": ["legal_form", "legal_name"],
        "naf": ["activity_code_naf", "naf"], "address": ["headquarters_address", "address"],
        "dirigeant": ["director", "dirigeant", "ceo"], "capital": ["capital"],
        "ville": ["city", "ville"], "code_postal": ["postal_code", "code_postal"],
    }
    attr_map = {
        "email": "email", "linkedin": "linkedin", "website": "website", "siren": "siren",
        "siret": "siret", "legal_form": "forme_juridique", "naf": "naf",
        "dirigeant": "dirigeant", "capital": "capital", "ville": "ville", "code_postal": "code_postal",
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
    return best

async def process_row(row: ExcelRow, agent, idx: Optional[int] = None, total: Optional[int] = None) -> List[dict]:
    """
    Harvests phones and stores them with confidence scores in enriched_fields.
    Returns a list of dicts: {'num': ..., 'score': ..., 'source': ...}
    """
    if row.status == "DONE" and not config.REPROCESS_FAILED_ROWS:
        logger.info(f"[Agent] Row #{row.row_index} SKIPPED — status={row.status}.")
        return []

    progress_str = f"{idx}/{total}" if idx and total else f"#{row.row_index}"
    siren_log = row.siren if row.siren else "N/A"
    logger.info(f"🔍 [Verification] Row {progress_str} | Target: '{row.nom}' | SIREN: {siren_log} | Localité: '{row.adresse}'")
    
    row.processing_start_ts = time.perf_counter()
    harvested = [] # List of {'num', 'score', 'source'}

    def add_unique(num, score, source):
        norm = normalize_phone(num)
        if not norm: return
        # Avoid duplicate numbers in same row
        if any(h['num'] == norm for h in harvested): return
        harvested.append({"num": norm, "score": score, "source": source})

    nom, adr = (row.nom or row.siren or ""), (row.adresse or "")
    
    # Existing phones to avoid duplication
    existing = set()
    if row.phone: existing.add(normalize_phone(row.phone))

    # 1. AI Mode Searches (High Confidence)
    for prompt_key, tag in [(config.AI_MODE_SEARCH_PROMPT, "ai_std"), (config.AI_MODE_EXPERT_PROMPT, "ai_expert")]:
        prompt = prompt_key.format(nom=nom, adresse=adr)
        ai_raw = await agent.search_google_ai_mode(prompt)
        if ai_raw:
            row.raw_ai_responses.append({"text": ai_raw, "source": tag, "query": prompt[:100]})
            candidates = extract_phones(ai_raw, source_label=tag)
            for p in candidates:
                add_unique(p, 97, tag)
            _fill_row_from_ai_mode(ai_raw, row)

    # 2. Knowledge Panel (Highest Confidence)
    if row.nom:
        kp_phone = await _search_knowledge_panel_phone(row, agent, f"{row.nom} {adr}")
        if kp_phone:
            add_unique(kp_phone, 99, "google_kp")

    # 3. Web Scraping (Medium Confidence)
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
        row.status = "DONE"
        # Store full list in enriched_fields for column expansion
        row.enriched_fields["phone_list"] = harvested
        logger.info(f"🏆 [Row {progress_str}] HARVESTED {len(harvested)} numbers. Best: {row.phone} | Time: {elapsed}s")
    else:
        row.status = "NO TEL"
        logger.warning(f"🔦 [Row {progress_str}] DEPLETED: No phone found | Time: {elapsed}s")

    return harvested
