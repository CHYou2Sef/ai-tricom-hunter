import logging
from excel.reader import ExcelRow
from enrichment.row_enricher import enrich_row as base_enrich_row

logger = logging.getLogger("Enricher")

def enrich_row(row: ExcelRow):
    """
    Wrapper for enrichment logic.
    Source priority: google_ai_mode (0.97) > aeo_schema (1.00) > gemini_json (0.90)
    Never overwrite field with existing non-empty value.
    """
    try:
        # Calls the existing implementation in enrichment/
        base_enrich_row(row)
    except Exception as e:
        logger.error(f"Enrichment error for row {row.row_index}: {e}")
