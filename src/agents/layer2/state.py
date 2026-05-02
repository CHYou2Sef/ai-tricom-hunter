"""
Layer 2 — Social URL Fallback State Schema
TypedDict that carries all data through the Layer 2 LangGraph.
"""
from __future__ import annotations
from typing import TypedDict, Optional, List, Dict, Any


class Layer2State(TypedDict):
    # ── Input ──────────────────────────────────────────────────────
    row_index:        int
    company_name:     str
    company_address:  str
    siren:            str
    discovered_urls:  Dict[str, List[str]]   # {"facebook": [...], "linkedin": [...], "website": [...]}

    # ── Routing ────────────────────────────────────────────────────
    urls_to_scrape:   List[Dict[str, str]]   # [{"url": "...", "source_type": "facebook"}]
    enabled_sources:  List[str]              # configurable allow-list

    # ── Scraping results ───────────────────────────────────────────
    scraped_results:  List[Dict[str, Any]]   # raw page texts + metadata per URL
    phone_candidates: List[Dict[str, Any]]   # {"num": ..., "score": ..., "source": ...}

    # ── Outcome ────────────────────────────────────────────────────
    best_phone:       Optional[str]
    confidence:       int                    # 0-100
    final_status:     str                    # "FOUND" | "NOT_FOUND" | "DEAD_LETTER"
    error_log:        List[str]
    retry_count:      int
