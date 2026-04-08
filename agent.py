"""
╔══════════════════════════════════════════════════════════════════════════╗
║  agent.py  —  Core Processing Engine (ASYNC VERSION)                     ║
║                                                                          ║
║  This is the BRAIN of the system. It takes a list of ExcelRow objects,   ║
║  runs the AI search for each one, extracts phone numbers, updates the    ║
║  status, and triggers the save to JSON + Excel.                          ║
║                                                                          ║
║  BEGINNER NOTE:                                                          ║
║    This file connects all the other modules together.                    ║
║    Think of it as the "manager" that calls each "worker" module.         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import sys
import time
import random
import asyncio
import re
import json
import pandas as pd
from typing import List, Dict, Any, Optional, Tuple

import config
from excel.reader import ExcelRow, read_excel, sync_with_previous_results
from excel.writer import save_results, save_subset_to_excel
from utils.logger import get_logger, alert
from utils.metrics import PerformanceTracker
from utils.anti_bot import action_delay_async, human_delay
from utils.text_cleaner import clean_html_to_text
from search.phone_extractor import extract_phones, get_best_phone, normalize_phone
from browser.hybrid_engine import HybridAutomationEngine
from enrichment.row_enricher import enrich_row

logger = get_logger(__name__)

# Counter for consecutive CAPTCHA blocks
_captcha_streak = 0
_captcha_lock = asyncio.Lock()

# Cache the winner of the benchmark to avoid running it for every file
_cached_engine = None

# Agent Pool for parallel workers
_agent_pool = asyncio.Queue()

async def init_agent_pool(count: int):
    """Pre-initialize a pool of browser hybrid engines."""
    logger.info(f"[AgentPool] Initializing {count} workers (Default Tier: {config.HYBRID_DEFAULT_TIER})...")
    for i in range(count):
        from browser.hybrid_engine import HybridAutomationEngine
        agent = HybridAutomationEngine(worker_id=i+1)
        # Pre-warm the default tier for immediate speed
        await agent.start_tier(config.HYBRID_DEFAULT_TIER)
        await _agent_pool.put(agent)

async def close_agent_pool():
    """Close all workers in the pool."""
    while not _agent_pool.empty():
        agent = await _agent_pool.get()
        await agent.close()

def get_browser_agent(worker_id: int = 0):
    """
    Create and return the appropriate browser engine.
    Now defaults to the HybridAutomationEngine which handles tier switching.
    """
    from browser.hybrid_engine import HybridAutomationEngine
    return HybridAutomationEngine(worker_id=worker_id)

async def human_delay_async(min_sec: float = config.MIN_DELAY_SECONDS, max_sec: float = config.MAX_DELAY_SECONDS):
    delay = random.uniform(min_sec, max_sec)
    logger.debug(f"[AntiBot] Sleeping {delay:.2f}s (human delay)")
    await asyncio.sleep(delay)

def sync_with_previous_results(rows: List[ExcelRow], filepath: str) -> int:
    """JSON audit synchronization is disabled. Returns 0."""
    return 0

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
    logger.info(f"    [Tier 0] Knowledge Panel Search: {query}")

    success = await agent.submit_google_search(query)
    if not success:
        return None

    await asyncio.sleep(3)
    
    phone = await agent.extract_knowledge_panel_phone()
    if phone:
        normalized = normalize_phone(phone)
        if normalized:
            row.raw_ai_responses.append({
                "text":   f"Knowledge Panel Phone Found: {normalized}",
                "source": "google_kp",
                "query":  query,
            })
            logger.info(f"✨ [Tier 0] GEMINI.md method SUCCESS: {normalized}")
            return normalized
    return None

async def _search_and_extract_phone(row: ExcelRow, agent, query: str, source_tag: str) -> Tuple[Optional[str], Optional[str]]:
    row.search_queries_used.append(query)
    content = await agent.search_google_ai(query)

    if content:
        row.raw_ai_responses.append({
            "text":   content,
            "source": source_tag,
            "query":  query,
        })

    phone = await _extract_aeo_phone(agent)

    if not phone and content:
        phones = extract_phones(content)
        phone = get_best_phone(phones)

    return phone, content

async def process_row(row: ExcelRow, agent) -> None:
    global _captcha_streak

    # Skip only DONE rows. "SKIP" and "NO TEL" are re-evaluated if REPROCESS_FAILED_ROWS is True.
    can_reprocess = config.REPROCESS_FAILED_ROWS and row.status in ("SKIP", "NO TEL")
    if row.status == "DONE" or (row.status in ("SKIP", "NO TEL") and not config.REPROCESS_FAILED_ROWS):
        logger.info(f"[Agent] Row #{row.row_index} SKIPPED — status={row.status}.")
        return

    logger.info(f"[Agent] Processing row #{row.row_index} | {row.get_search_name()}")
    row.processing_start_ts = time.perf_counter()
    best_phone = None

    # --- 1. PRIMARY: AI Search (Waterfall) ---
    nom, adr = (row.nom or row.siren or ""), (row.adresse or "")
    for prompt_key, tag in [(config.AI_MODE_SEARCH_PROMPT, "ai_std"), (config.AI_MODE_EXPERT_PROMPT, "ai_expert")]:
        prompt = prompt_key.format(nom=nom, adresse=adr)
        ai_raw = await agent.search_google_ai_mode(prompt)
        if ai_raw:
            row.raw_ai_responses.append({"text": ai_raw, "source": tag, "query": prompt[:100]})
            best_phone = _fill_row_from_ai_mode(ai_raw, row)
            if best_phone: break

    # --- 2. FALLBACK: Direct Scraping ---
    if not best_phone:
        # Knowledge Panel
        if row.nom:
            best_phone = await _search_knowledge_panel_phone(row, agent, f"{row.nom} {adr}")
        
        # Domain Search
        if not best_phone:
            q = build_search_query(row)
            if q:
                res, _ = await _search_and_extract_phone(row, agent, q, "google_scrap")
                best_phone = res

    row.phone   = best_phone
    row.status  = "DONE" if best_phone else "NO TEL"
    row.processing_end_ts = time.perf_counter()


def _fill_row_from_ai_mode(raw_text: str, row: ExcelRow) -> Optional[str]:
    """
    Parses Google AI Mode's JSON response and fills ALL row fields:
    phone, email, linkedin, siren, siret, legal_form, address, website.
    Returns the best phone found, or None.
    """
    from browser.playwright_agent import PlaywrightAgent
    data = PlaywrightAgent.parse_ai_mode_json(raw_text)
    if not data:
        logger.debug("[AI Mode Parser] No JSON found in response.")
        return None

    logger.debug(f"[AI Mode Parser] Parsed keys: {list(data.keys())}")

    # ─ Extract phone ─
    phones_raw = data.get("phone_numbers") or data.get("telephone") or data.get("phone")
    best = None
    if isinstance(phones_raw, list) and phones_raw:
        best = normalize_phone(phones_raw[0])
    elif isinstance(phones_raw, str):
        best = normalize_phone(phones_raw)
    # Also fall back to regex on the raw text
    if not best:
        candidates = extract_phones(raw_text)
        best = get_best_phone(candidates)

    # ─ Fill enriched_fields & Row Attributes ─
    field_map = {
        "email":       ["email"],
        "linkedin":    ["linkedin", "linkedin_url"],
        "website":     ["website", "website_url"],
        "siren":       ["siren"],
        "siret":       ["siret"],
        "legal_form":  ["legal_form", "legal_name"],
        "naf":         ["activity_code_naf", "naf"],
        "address":     ["headquarters_address", "address"],
        "dirigeant":   ["director", "dirigeant", "ceo"],
        "capital":     ["capital"],
        "ville":       ["city", "ville"],
        "code_postal": ["postal_code", "code_postal"],
    }
    
    # Map for setting core row attributes (if they are empty)
    # Row Key (enriched_fields) -> Attribute Name (ExcelRow instance)
    attr_map = {
        "email":      "email",
        "linkedin":   "linkedin",
        "website":    "website",
        "siren":      "siren",
        "siret":      "siret",
        "legal_form": "forme_juridique",
        "naf":        "naf",
        "dirigeant":  "dirigeant",
        "capital":    "capital",
        "ville":      "ville",
        "code_postal":"code_postal",
    }
    
    for row_key, json_keys in field_map.items():
        for jk in json_keys:
            val = data.get(jk)
            # Handle nested collections (dict or list)
            if isinstance(val, dict):
                val = ", ".join(str(v) for v in val.values() if v)
            elif isinstance(val, list):
                val = ", ".join(str(v) for v in val if v)
            if val and str(val).upper() not in ("NOT_FOUND", "NONE", "", "NULL"):
                clean_val = str(val).strip()
                # 1. Fill the audit metadata
                row.enriched_fields[row_key] = {
                    "value":      clean_val,
                    "source":     "google_ai_mode",
                    "confidence": 0.97,
                }
                # 2. Fill the row attribute directly if it's currently empty
                attr = attr_map.get(row_key)
                if attr and not getattr(row, attr, None):
                    setattr(row, attr, clean_val)
                    logger.debug(f"[AI Mode Parser] Filled attribute '{attr}': {clean_val}")
                break
    return best

async def _extract_aeo_phone(agent) -> Optional[str]:
    aeo_data = await agent.extract_aeo_data()
    if not aeo_data:
        return None
    logger.info(f"    [AEO] Scanning {len(aeo_data)} JSON-LD blocks for Schema.org data.")
    for block in aeo_data:
        tel = block.get("telephone") or block.get("contactPoint", {}).get("telephone")
        if tel:
            logger.info(f"    [AEO] Found telephone in structured data: {tel}")
            return tel
    return None

async def _extract_geo_phone(row: ExcelRow, agent, page_content: str) -> Optional[str]:
    logger.info(f"    [GEO] No conclusive phone found. Initializing Gemini RAG fallback...")
    # Use the new robust cleaner to remove JS/Style tags
    context = clean_html_to_text(page_content)[:8000].strip()
    
    geo_prompt = config.GEO_FALLBACK_PROMPT.format(
        nom=row.nom or row.siren,
        adresse=row.adresse,
        raw_web_context=context
    )
    
    await human_delay_async(1, 2)
    geo_response = await agent.search_gemini_ai(geo_prompt)
    
    if geo_response:
        row.raw_ai_responses.append({
            "text":   geo_response,
            "source": "gemini_json",
            "query":  geo_prompt[:200],
        })
        try:
            json_match = re.search(r'\{.*\}', geo_response, re.DOTALL)
            if json_match:
                import json
                res = json.loads(json_match.group(0).strip())
                tel = res.get("telephone")
                if tel and str(tel).upper() != "NOT_FOUND":
                    logger.info(f"    [GEO] Extracted phone via RAG: {tel} ({res.get('source')})")
                    return tel
        except Exception as e:
            logger.debug(f"    [GEO] JSON parsing failed: {e}")
    return None

async def _handle_captcha_streak_async(page_content: Optional[str], agent=None) -> None:
    global _captcha_streak
    async with _captcha_lock:
        if page_content is None:
            _captcha_streak += 1
            if _captcha_streak >= config.MAX_CONSECUTIVE_CAPTCHA:
                if getattr(config, "PROXY_ROTATION_ACTIVATES_ON_BAN", False):
                    logger.critical(f"[Agent] {_captcha_streak} consecutive blocks! 🛡️ ACTIVATING PROXY ROTATION...")
                    config.PROXY_ENABLED = True
                    if agent and hasattr(agent, "rotate_proxy"):
                        await agent.rotate_proxy()
                    _captcha_streak = 0
                else:
                    logger.critical(f"[Agent] {_captcha_streak} consecutive blocks! Pausing 60s...")
                    await asyncio.sleep(60)
                    _captcha_streak = 0
        else:
            _captcha_streak = 0 

def _fill_missing_siren(row: ExcelRow, page_content: str) -> None:
    match = re.search(r'\b(\d{9})\b', page_content)
    if match:
        row.siren = match.group(1)
        logger.info(f"    [AI] Found missing SIREN: {row.siren}")


async def _worker_process_row(row: ExcelRow, sem: asyncio.Semaphore, save_lock: asyncio.Lock, rows: List[ExcelRow], filepath: str, tracker: PerformanceTracker, idx: int, total: int) -> ExcelRow:
    async with sem:
        # Get an agent from the pool — agent.worker_id identifies which Chrome window
        agent = await _agent_pool.get()
        worker_id  = getattr(agent, "worker_id", "?")
        row_start  = time.perf_counter()

        logger.info(
            f"[🔵 Worker-{worker_id}] ► Row {idx}/{total} │ #{row.row_index} │ {row.nom or row.siren or 'N/A'}"
        )

        try:
            await process_row(row, agent)
            if row.status != "SKIP":
                await asyncio.to_thread(enrich_row, row)

            if row.status not in ("DONE", "NO TEL", "SKIP"):
                await human_delay_async()
        except Exception as e:
            logger.error(f"[Worker-{worker_id}] ❌ Error on row #{row.row_index}: {e}", exc_info=True)
        finally:
            # Return the agent to the pool
            await _agent_pool.put(agent)

        # ── Per-row performance log ──
        elapsed   = time.perf_counter() - row_start
        icon      = "✅" if row.phone else "❌"
        source    = ""
        if row.raw_ai_responses:
            source = row.raw_ai_responses[-1].get("source", "")

        logger.info(
            f"[🔵 Worker-{worker_id}] {icon} Row #{row.row_index} │ "
            f"status={row.status} │ phone={row.phone or 'None'} │ "
            f"source={source or 'N/A'} │ ⏱ {elapsed:.1f}s"
        )

        duration = elapsed
        tracker.track_row(duration, row.status)

        # Progress & checkpoint every 10 rows
        if idx % 10 == 0 or idx == total:
            done_count = sum(1 for r in rows if r.phone)
            pct        = round(done_count / max(len(rows), 1) * 100, 1)
            logger.info(
                f"[📊 Progress] {idx}/{total} rows done │ "
                f"✅ Found: {done_count} ({pct}%) │ "
                f"❌ No Tel: {sum(1 for r in rows if r.status == 'NO TEL')}"
            )
            async with save_lock:
                await asyncio.to_thread(save_results, rows, filepath)

    return row

async def process_file_async(filepath: str) -> None:
    logger.info(f"[Agent] ━━━ Starting file (Async): {os.path.basename(filepath)} ━━━")

    # Read excel synchronously
    rows, mapping = await asyncio.to_thread(read_excel, filepath)
    if not rows:
        logger.warning(f"[Agent] No rows found in {filepath}. Skipping.")
        return

    tracker = PerformanceTracker()
    tracker.start_file_processing()

    try:
        # Sync with JSON
        await asyncio.to_thread(sync_with_previous_results, rows, filepath)

        # Select rows to process: 
        # Always PENDING/None, and conditionally NO TEL/SKIP based on config.
        if config.REPROCESS_FAILED_ROWS:
            rows_to_process = [r for r in rows if r.status != "DONE"]
        else:
            rows_to_process = [r for r in rows if r.status not in ("DONE", "NO TEL", "SKIP")]

        total = len(rows_to_process)
        if total > 0:
            save_lock = asyncio.Lock()
            workers = config.MAX_CONCURRENT_WORKERS
            sem = asyncio.Semaphore(workers)
            
            tasks = []
            for idx, r in enumerate(rows_to_process, start=1):
                task = asyncio.create_task(
                    _worker_process_row(r, sem, save_lock, rows, filepath, tracker, idx, total)
                )
                tasks.append(task)
            
            await asyncio.gather(*tasks)
        
        await asyncio.to_thread(save_results, rows, filepath)
        
    except asyncio.CancelledError:
        logger.warning("[Agent] Cancelled. Saving partial results...")
        await asyncio.to_thread(save_results, rows, filepath)
        raise
    except KeyboardInterrupt:
        logger.warning("[Agent] Interrupted. Saving partial results...")
        await asyncio.to_thread(save_results, rows, filepath)
        raise
    except Exception as e:
        logger.error(f"[Agent] Unexpected error: {e}", exc_info=True)
        await asyncio.to_thread(save_results, rows, filepath)

    tracker.end_file_processing()
    
    logger.info(tracker.format_console_report())
    
    done    = sum(1 for r in rows if r.status == "DONE")
    no_tel  = sum(1 for r in rows if r.status == "NO TEL")
    skipped = sum(1 for r in rows if r.status == "SKIP")

    logger.info(
        f"[Agent] ━━━ Finished: {os.path.basename(filepath)} ━━━\n"
        f"         ✅ DONE   : {done}\n"
        f"         📵 NO TEL : {no_tel}\n"
        f"         ⏭️  SKIP   : {skipped}"
    )

    # ── POST-PROCESSING: ARCHIVE & RECYCLE ──
    await finalize_file_processing(rows, filepath)


async def finalize_file_processing(rows: List[ExcelRow], original_filepath: str) -> None:
    """
    Post-processing after a file is fully processed:

    1. ✅ DONE rows  → archived to output/Archived_Results/
    2. ❌ NO TEL + ⏱ SKIP rows → archived to output/Archived_Failed/
    3. Original file is deleted.
    """
    from pathlib import Path

    orig_path   = Path(original_filepath)
    # Remove "_DONE" / "RETRY_" / "part" from the base name to clean it up
    clean_stem = orig_path.stem
    for prefix in ["RETRY_", "_DONE", "part"]:
        import re
        clean_stem = re.sub(rf"^{prefix}+|{prefix}.*$", "", clean_stem)
    # Also strip if the user sent it formatted weirdly
    clean_stem = clean_stem.strip("_")

    suffix      = ".xlsx"  # Always save as xlsx

    success_rows = [r for r in rows if r.phone or r.status == "DONE"]
    retry_rows   = [r for r in rows if r.status in ("NO TEL", "SKIP", "PENDING")]

    logger.info(
        f"[Post-Process] ✅ {len(success_rows)} DONE │ "
        f"❌ {len(retry_rows)} FAILED (Skipped/No Tel)"
    )

    # ── ROUTING LOGIC ──
    # Determine the destination folder based on where the source file lived.
    # Note: If it's a chunk, its grandparent is the bucket.
    parent_dir = orig_path.parent.name
    if parent_dir == "chunks_processing":
        parent_dir = orig_path.parent.parent.name
    
    destination_dir = config.OUTPUT_ARCHIVE_DIR
    if "RS" in parent_dir:
        destination_dir = config.OUTPUT_RS_ADR
    elif "sir" in parent_dir or "SIR" in parent_dir:
        destination_dir = config.OUTPUT_SIR_ADR
    elif "std" in parent_dir or "STD" in parent_dir:
        destination_dir = config.OUTPUT_RS_ADR # Standard contains RS
    
    # ── 1. ARCHIVE DONE ROWS ──
    if success_rows:
        destination_dir.mkdir(parents=True, exist_ok=True)
        archive_path = destination_dir / f"{clean_stem}{suffix}"
        if archive_path.exists():
            ts = time.strftime("%H%M%S")
            archive_path = config.OUTPUT_ARCHIVE_DIR / f"{clean_stem}_{ts}{suffix}"
        logger.info(f"[Post-Process] 📦 Archiving DONE → {archive_path.name}")
        await asyncio.to_thread(save_subset_to_excel, success_rows, archive_path)

    # ── 2. ARCHIVE FAILED ROWS (No automatic recycling) ──
    if retry_rows:
        config.OUTPUT_FAILED_DIR.mkdir(parents=True, exist_ok=True)
        failed_path = config.OUTPUT_FAILED_DIR / f"{clean_stem}_FAILED{suffix}"
        if failed_path.exists():
            ts = time.strftime("%H%M%S")
            failed_path = config.OUTPUT_FAILED_DIR / f"{clean_stem}_FAILED_{ts}{suffix}"
        logger.info(f"[Post-Process] 📦 Archiving FAILED → {failed_path.name}")
        await asyncio.to_thread(save_subset_to_excel, retry_rows, failed_path)

    # ── 3. DELETE ORIGINAL ──
    # OLD: retry saved in same directory → orig_path.parent / "RETRY_{filename}"
    try:
        os.remove(original_filepath)
        logger.info(f"[Post-Process] 🗑️ Cleaned up original: {orig_path.name}")
    except Exception as e:
        logger.warning(f"[Post-Process] Could not delete {orig_path.name}: {e}")


async def _deep_scrape_website(row: ExcelRow, agent) -> Optional[str]:
    """
    Tries to find the official website, crawls it (home + contact),
    and uses Gemini (IA Mode) to extract ALL B2B data.
    """
    # 1. Identify Official Website URL (if not already known)
    website_url = row.enriched_fields.get("website", {}).get("value")
    
    if not website_url:
        # Quick search to find the website
        search_query = f'"{row.nom}" "{row.adresse or ""}" official website'
        logger.info(f"   [Tier 0.5] Finding official website: {search_query}")
        content = await agent.search_google_ai(search_query)
        if content:
            import re
            # Simple heuristic: find the first <a> link that isn't google/social media
            # Better: use regex for common patterns
            urls = re.findall(r'https?://[^\s<>"]+', content)
            
            # Expanded heuristic to avoid common non-official sites
            banned_domains = [
                "google", "pappers.fr", "societe.com", "infogreffe",
                "facebook.com", "linkedin.com", "twitter.com", "instagram.com",
                "pagesjaunes.fr", "annuaire-entreprises", "mappy", "118000"
            ]
            
            for u in urls:
                if any(x in u for x in banned_domains):
                    continue
                website_url = u
                logger.info(f"   [Tier 0.5] Found candidate website: {u}")
                row.enriched_fields["website"] = {"value": u, "source": "google_heuristic", "confidence": 0.8}
                break

    if not website_url:
        return None

    # 2. Crawl multiple pages
    scraped_text = await agent.crawl_website(website_url)
    if not scraped_text or len(scraped_text) < 200:
        return None

    # 3. IA Mode (Gemini) Extraction
    # Clean text before sending to IA to avoid JS contamination
    context = clean_html_to_text(scraped_text)[:12000]
    prompt = config.DEEP_SCRAPE_PROMPT.format(raw_web_context=context)
    logger.info(f"   [IA Mode] analyzing official website data...")
    
    # We call search_gemini_ai which opens a "new tap" (implicitly in the context)
    ia_response = await agent.search_gemini_ai(prompt)
    
    if ia_response:
        row.raw_ai_responses.append({
            "text": ia_response,
            "source": f"IA_Mode_Website:{website_url}",
            "query": "Deep Scrape Prompt"
        })
        
        # 4. Parse JSON
        json_match = re.search(r'\{.*\}', ia_response, re.DOTALL)
        if json_match:
            try:
                data = json.loads(json_match.group(0).strip())
                logger.info(f"   ✨ [IA Mode] Success! Extracted: {list(data.keys())}")
                
                phone = data.get("telephone")
                # Update row enriched fields
                fields_to_update = {
                    "email": "email",
                    "linkedin": "linkedin",
                    "facebook": "facebook",
                    "instagram": "instagram",
                    "twitter": "twitter",
                    "address": "adresse_physique",
                    "legal_name": "nom_officiel"
                }
                for row_key, json_key in fields_to_update.items():
                    val = data.get(json_key)
                    if val and str(val).upper() not in ("NOT_FOUND", "NONE", ""):
                        row.enriched_fields[row_key] = {
                            "value": val,
                            "source": "IA_Mode_Website",
                            "confidence": data.get("confiance", 0.9)
                        }
                
                if phone and str(phone).upper() != "NOT_FOUND":
                    return normalize_phone(phone)
            except Exception as e:
                logger.debug(f"   [IA Mode] JSON Parse Error: {e}")
                
    return None

