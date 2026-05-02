"""
Layer 2 — Social URL Fallback Entry Point

Public API:
    await run_layer2_graph(row, social_links, agent)

Called from phone_hunter.process_row() after Layer 1 is exhausted.
"""
from __future__ import annotations

import asyncio
import time
from typing import Optional, Dict, List, Any

from domain.excel.reader import ExcelRow
from core.logger import get_logger
from .state import Layer2State

logger  = get_logger(__name__)
_graph  = None   # compiled graph singleton — built once at first call


def _get_graph():
    global _graph
    if _graph is None:
        from .graph import build_layer2_graph
        _graph = build_layer2_graph()
        logger.debug("[Layer2] Graph compiled and cached.")
    return _graph


async def run_layer2_graph(
    row:             ExcelRow,
    social_links:    Dict[str, List[str]],
    agent=None,
    enabled_sources: Optional[List[str]] = None,
) -> Optional[Dict[str, Any]]:
    """
    Run the Layer 2 fallback LangGraph for a given ExcelRow.

    Args:
        row:             The ExcelRow that Layer 1 failed to resolve.
        social_links:    {"facebook": [...], "linkedin": [...], "website": [...]}
        agent:           Unused — reserved for future browser-tier escalation.
        enabled_sources: Which source types to activate (default: all enabled in config).

    Returns:
        {"num": ..., "score": ..., "source": "layer2"} or None.
    """
    if enabled_sources is None:
        from core import config
        raw = getattr(config, "LAYER2_ENABLED_SOURCES", "facebook,linkedin,website")
        enabled_sources = [s.strip() for s in raw.split(",") if s.strip()]

    initial: Layer2State = {
        "row_index":        row.row_index,
        "company_name":     row.nom or row.siren or "Unknown",
        "company_address":  row.adresse or "France",
        "siren":            row.siren or "",
        "discovered_urls":  social_links,
        "urls_to_scrape":   [],
        "enabled_sources":  enabled_sources,
        "scraped_results":  [],
        "phone_candidates": [],
        "best_phone":       None,
        "confidence":       0,
        "final_status":     "NOT_STARTED",
        "error_log":        [],
        "retry_count":      0,
    }

    try:
        from core import config
        from common.metrics import get_layer_telemetry
        telemetry = get_layer_telemetry()
        start_ts  = time.time()

        timeout = float(getattr(config, "LAYER2_TIMEOUT_SEC", 30))
        graph   = _get_graph()

        # Graph is synchronous (tool calls are blocking httpx/requests).
        # Run in thread pool so we don't block the asyncio event loop.
        loop        = asyncio.get_event_loop()
        final: Layer2State = await asyncio.wait_for(
            loop.run_in_executor(None, graph.invoke, initial),
            timeout=timeout,
        )

        duration = time.time() - start_ts
        success  = final.get("best_phone") is not None
        
        # Track sources used
        source_counts = {}
        for res in final.get("scraped_results", []):
            st = res.get("source_type", "unknown")
            source_counts[st] = source_counts.get(st, 0) + 1

        telemetry.record(
            "Layer 2", 
            success, 
            duration, 
            urls_tried=len(final.get("urls_to_scrape", [])),
            candidates=len(final.get("phone_candidates", [])),
            **source_counts
        )
        telemetry.save_to_json()

        if final.get("best_phone"):
            candidates = final.get("phone_candidates", [])
            src = candidates[0].get("source", "layer2") if candidates else "layer2"
            result = {
                "num":    final["best_phone"],
                "score":  final["confidence"],
                "source": src,
            }
            logger.info(
                f"✨ [Layer2] Row #{row.row_index} → {result['num']} "
                f"(conf: {result['score']}%, src: {result['source']}) | {duration:.2f}s"
            )
            # Persist provenance onto the row for downstream reporting
            row.enriched_fields["layer2_source"] = src
            return result

    except asyncio.TimeoutError:
        logger.warning(f"[Layer2] Timeout ({timeout}s) for row #{row.row_index}")
    except Exception as exc:
        logger.error(f"[Layer2] Graph error for row #{row.row_index}: {exc}", exc_info=True)

    return None
