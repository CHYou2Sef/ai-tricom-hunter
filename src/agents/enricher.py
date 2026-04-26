"""
╔══════════════════════════════════════════════════════════════════════════╗
║  agents/enricher.py                                                      ║
║                                                                          ║
║  Enrichment Agent Wrapper                                                ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Thin async wrapper around the domain enrichment pipeline.             ║
║    Called by the orchestrator after phone extraction is complete.        ║
║                                                                          ║
║  SOURCE PRIORITY (highest → lowest):                                     ║
║    aeo_schema   : 1.00  — structured JSON-LD from official sites         ║
║    gemini_json  : 0.90  — Google Gemini AI response in JSON format       ║
║    google_ai    : 0.75  — Google AI Overview text                        ║
║                                                                          ║
║  RULE: Never overwrite a field that already has a non-empty input value  ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import logging
from domain.excel.reader import ExcelRow
from domain.enrichment.row_enricher import enrich_row as base_enrich_row

logger = logging.getLogger("Enricher")

async def enrich_row(row: ExcelRow, agent=None):
    """
    Enrich a single row with secondary data (email, website, SIRET, etc.).

    Args:
        row   : ExcelRow instance to enrich in-place
        agent : Browser agent (optional, for future use)

    Returns:
        None (mutates row.enriched_fields directly)
    """
    try:
        # Delegate to the domain-level enrichment engine
        base_enrich_row(row)
    except Exception as e:
        logger.error(f"Enrichment error for row {row.row_index}: {e}")
