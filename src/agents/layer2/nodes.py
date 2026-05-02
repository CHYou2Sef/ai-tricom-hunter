"""
Layer 2 — Social URL Fallback Node Functions

All nodes are pure functions: (Layer2State) -> Layer2State.
Tool instances are module-level singletons (created once, reused per call).
"""
import json
import time
from pathlib import Path
from typing import List

from .state import Layer2State
from .tools import FacebookPhoneTool, LinkedInPhoneTool, WebsitePhoneTool
from domain.search.phone_extractor import extract_phones, get_best_phone, normalize_phone
from core import config
from core.logger import get_logger

logger = get_logger(__name__)

# ── Tool singletons — instantiated once at import time ──────────────────
_fb_tool  = FacebookPhoneTool()
_li_tool  = LinkedInPhoneTool()
_web_tool = WebsitePhoneTool()

# Confidence scores by source (below Layer 1 high-confidence threshold of 90)
_SCORE_MAP = {
    "facebook": 88,
    "linkedin": 85,
    "website":  82,
}


# ── Node 1: Classify & prioritise URLs ──────────────────────────────────
def classify_urls_node(state: Layer2State) -> Layer2State:
    """
    Convert discovered_urls dict → ordered list of {url, source_type}.

    Priority order: facebook > linkedin > website
    (social /about pages expose phones more often than generic sites).
    Max 2 URLs per source type to bound total scraping time.
    """
    discovered = state.get("discovered_urls", {})
    enabled    = set(state.get("enabled_sources", ["facebook", "linkedin", "website"]))
    max_per    = int(getattr(config, "LAYER2_MAX_URLS_PER_SOURCE", 2))

    ordered: List[dict] = []
    for src_type in ("facebook", "linkedin", "website"):
        if src_type not in enabled:
            continue
        for url in (discovered.get(src_type) or [])[:max_per]:
            ordered.append({"url": url, "source_type": src_type})

    logger.info(
        f"[L2|classify] Row #{state['row_index']} — "
        f"{len(ordered)} URL(s) queued: {[i['source_type'] for i in ordered]}"
    )
    return {**state, "urls_to_scrape": ordered}


# ── Node 2a: Facebook scraper ────────────────────────────────────────────
def scrape_facebook_node(state: Layer2State) -> Layer2State:
    """Scrape all facebook-type URLs using FacebookPhoneTool."""
    results = list(state.get("scraped_results", []))
    errors  = list(state.get("error_log", []))

    for item in state.get("urls_to_scrape", []):
        if item["source_type"] != "facebook":
            continue
        logger.info(f"[L2|facebook] Scraping {item['url']}")
        result = _fb_tool._run(item["url"])
        results.append({**result, "source_type": "facebook"})
        if result.get("error"):
            errors.append(f"facebook:{item['url']}:{result['error']}")
        # Respect rate limit — social platforms ban fast crawlers
        time.sleep(config.MIN_DELAY_SECONDS)

    return {**state, "scraped_results": results, "error_log": errors}


# ── Node 2b: LinkedIn scraper ────────────────────────────────────────────
def scrape_linkedin_node(state: Layer2State) -> Layer2State:
    """Scrape all linkedin-type URLs using LinkedInPhoneTool."""
    results = list(state.get("scraped_results", []))
    errors  = list(state.get("error_log", []))

    for item in state.get("urls_to_scrape", []):
        if item["source_type"] != "linkedin":
            continue
        logger.info(f"[L2|linkedin] Scraping {item['url']}")
        result = _li_tool._run(item["url"])
        results.append({**result, "source_type": "linkedin"})
        if result.get("error"):
            errors.append(f"linkedin:{item['url']}:{result['error']}")
        time.sleep(config.MIN_DELAY_SECONDS)

    return {**state, "scraped_results": results, "error_log": errors}


# ── Node 2c: Website scraper ─────────────────────────────────────────────
def scrape_website_node(state: Layer2State) -> Layer2State:
    """Scrape all website-type URLs using WebsitePhoneTool."""
    results = list(state.get("scraped_results", []))
    errors  = list(state.get("error_log", []))

    for item in state.get("urls_to_scrape", []):
        if item["source_type"] != "website":
            continue
        logger.info(f"[L2|website] Scraping {item['url']}")
        result = _web_tool._run(item["url"])
        results.append({**result, "source_type": "website"})
        if result.get("error"):
            errors.append(f"website:{item['url']}:{result['error']}")

    return {**state, "scraped_results": results, "error_log": errors}


# ── Node 3: Aggregate all phone candidates ───────────────────────────────
def aggregate_node(state: Layer2State) -> Layer2State:
    """
    Collect all phone numbers from scraped_results, normalise them,
    and score them by source type.  De-duplicates by normalised number.
    """
    seen:       set  = set()
    candidates: list = []

    for res in state.get("scraped_results", []):
        src_type = res.get("source_type", "website")
        phone    = res.get("phone")

        # Fallback: regex over raw text (bio / about fields)
        if not phone:
            raw    = res.get("about") or res.get("text") or ""
            phones = extract_phones(raw, source_label=src_type)
            phone  = get_best_phone(phones)

        if not phone:
            continue

        norm = normalize_phone(phone)
        if not norm or norm in seen:
            continue

        seen.add(norm)
        candidates.append({
            "num":    norm,
            "score":  _SCORE_MAP.get(src_type, 80),
            "source": f"layer2_{src_type}",
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    logger.info(
        f"[L2|aggregate] Row #{state['row_index']} — "
        f"{len(candidates)} unique candidate(s)"
    )
    return {**state, "phone_candidates": candidates}


# ── Node 4: Validate best candidate ─────────────────────────────────────
def validate_node(state: Layer2State) -> Layer2State:
    """Pick the highest-scored candidate as the final answer."""
    candidates = state.get("phone_candidates", [])
    if not candidates:
        logger.info(f"[L2|validate] Row #{state['row_index']} — no candidates found")
        return {**state, "best_phone": None, "confidence": 0, "final_status": "NOT_FOUND"}

    best = candidates[0]
    logger.info(
        f"[L2|validate] ✅ Row #{state['row_index']} — "
        f"best={best['num']} score={best['score']} src={best['source']}"
    )
    return {
        **state,
        "best_phone":   best["num"],
        "confidence":   best["score"],
        "final_status": "FOUND",
    }


# ── Node 5: Dead Letter Queue ─────────────────────────────────────────────
def dead_letter_node(state: Layer2State) -> Layer2State:
    """
    Persist failed rows to a JSONL dead-letter log.
    These are picked up by REPROCESS_FAILED_ROWS or manual review.
    Never blocks — always returns successfully.
    """
    logger.warning(
        f"[L2|DeadLetter] Row #{state['row_index']} ({state['company_name']}) "
        f"exhausted all Layer 2 URLs."
    )
    _write_dead_letter(state)
    return {**state, "final_status": "DEAD_LETTER"}


def _write_dead_letter(state: Layer2State) -> None:
    """Append a JSONL record for operator review / requeue."""
    try:
        dl_path = Path(config.LOG_DIR) / "layer2_dead_letters.jsonl"
        record  = {
            "row_index":   state["row_index"],
            "company":     state["company_name"],
            "siren":       state["siren"],
            "address":     state["company_address"],
            "urls_tried":  [i["url"] for i in state.get("urls_to_scrape", [])],
            "candidates":  state.get("phone_candidates", []),
            "errors":      state.get("error_log", []),
        }
        with open(dl_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.debug(f"[L2|DeadLetter] Written to {dl_path}")
    except Exception as exc:
        # Never crash the graph because of logging failure
        logger.error(f"[L2|DeadLetter] Failed to write JSONL: {exc}")
