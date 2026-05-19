"""
fast_pipeline/pipeline.py - Fast Social Fallback Pipeline

DROPS LangGraph entirely. Uses direct async/await + asyncio.gather
for 3-5x faster parallel scraping.
"""

import asyncio
import logging
from typing import Dict, List, Optional, Any

from core import config
from core.logger import get_logger

from .parallel_scraper import ParallelSocialScraper, ScraperResult, select_best_result

logger = get_logger(__name__)


async def social_fallback_pipeline(
    row_index: int,
    company_name: str,
    company_address: str = "",
    siren: str = "",
    discovered_urls: Optional[Dict[str, List[str]]] = None,
    enabled_sources: Optional[List[str]] = None,
    timeout: float = 30.0,
) -> Dict[str, Any]:
    """
    Fast social fallback pipeline - replaces LangGraph Layer2.
    
    Args:
        row_index: Current row index
        company_name: Company name for search
        company_address: Company address for disambiguation
        siren: SIREN number for validation
        discovered_urls: {"facebook": [...], "linkedin": [...], "website": [...]}
        enabled_sources: List of sources to scrape ("facebook", "linkedin", "website")
        timeout: Max seconds for entire pipeline
    
    Returns:
        {"num": phone, "score": confidence, "source": source_type, "status": "FOUND"}
    """
    if discovered_urls is None:
        discovered_urls = {}
    if enabled_sources is None:
        enabled_sources = ["facebook", "linkedin", "website"]
    
    # Filter URLs by enabled sources
    filtered_urls = {
        src: discovered_urls.get(src, [])
        for src in enabled_sources
        if src in discovered_urls
    }
    
    if not filtered_urls:
        logger.debug(f"[Row {row_index}] No URLs discovered for fallback")
        return {"status": "NOT_FOUND", "num": None, "score": 0}
    
    logger.info(f"[Row {row_index}] FastPipeline: scraping {sum(len(v) for v in filtered_urls.values())} URLs")
    
    # Run PARALLEL scraping
    scraper = ParallelSocialScraper(
        row_index=row_index,
        company_name=company_name,
        company_address=company_address,
        siren=siren,
    )
    
    try:
        results = await asyncio.wait_for(
            scraper.scrape_all(filtered_urls, timeout=timeout),
            timeout=timeout
        )
    except asyncio.TimeoutError:
        logger.warning(f"[Row {row_index}] FastPipeline timed out after {timeout}s")
        return {"status": "TIMEOUT", "num": None, "score": 0, "errors": scraper.errors}
    
    # Select best result
    best = select_best_result(results)
    
    if best and best.phone:
        return {
            "status": "FOUND",
            "num": best.phone,
            "score": best.score,
            "source": best.source,
            "all_results": [
                {"phone": r.phone, "score": r.score, "source": r.source}
                for r in results if r.phone
            ],
            "errors": scraper.errors,
        }
    
    return {"status": "NOT_FOUND", "num": None, "score": 0, "errors": scraper.errors}
