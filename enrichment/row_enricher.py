"""
enrichment/row_enricher.py

Orchestrates the enrichment pipeline for a single ExcelRow.

Rules:
  1. Never overwrite a field that already has a non-empty value from the input file.
  2. Run field_extractor on EVERY collected AI response.
  3. When multiple responses provide the same field, pick the best by confidence.
  4. Record every decision in row.enriched_fields for full auditability.
"""

import time
from typing import TYPE_CHECKING

from enrichment.field_extractor import extract_all
from enrichment.confidence import SOURCE_WEIGHTS, best_value
from utils.logger import get_logger

if TYPE_CHECKING:
    from excel.reader import ExcelRow

logger = get_logger(__name__)


# ── Fields that can be enriched (= written back to the row if currently empty) ──
ENRICHABLE_FIELDS = [
    "nom", "adresse", "siren", "siret", "naf",
    "email", "website", "forme_juridique", "capital",
    "dirigeant", "code_postal", "ville", "effectif",
    "linkedin", "facebook", "instagram", "twitter",
]

# ── Map enricher field name → ExcelRow attribute name ──
FIELD_TO_ATTR = {
    "nom":             "nom",
    "adresse":         "adresse",
    "siren":           "siren",
    "siret":           "siret",
    "naf":             "naf",
    "email":           "email",
    "website":         "website",
    "forme_juridique": "forme_juridique",
    "capital":         "capital",
    "dirigeant":       "dirigeant",
    "code_postal":     "code_postal",
    "ville":           "ville",
    "effectif":        "effectif",
    "linkedin":        "linkedin",
    "facebook":        "facebook",
    "instagram":       "instagram",
    "twitter":         "twitter",
}


def enrich_row(row: "ExcelRow") -> None:
    """
    Main entry point. Call this after process_row() for every row.

    Mutates row in place:
      - Fills empty attributes with best extracted values
      - Populates row.enriched_fields with full audit metadata
    """
    row.processing_end_ts = time.perf_counter()

    # ── 1. Initialize or keep existing candidates (e.g. from Google AI Mode) ──
    # If _fill_row_from_ai_mode already populated enriched_fields, we keep them as candidates.
    candidates: dict[str, list] = {f: [] for f in ENRICHABLE_FIELDS}
    for field_name, info in getattr(row, "enriched_fields", {}).items():
        if field_name in candidates:
            candidates[field_name].append({
                "value":      info.get("value"),
                "source":     info.get("source", "google_ai_mode"),
                "confidence": info.get("confidence", 0.95),
            })

    if not row.raw_ai_responses:
        logger.debug(f"[Enricher] Row #{row.row_index} — no AI responses to scan.")
        # But we still continue to apply any candidates already found by the JSON parser
    else:
        # ── 2. Scan raw responses via Regex (for Tiers 1-5) ──
        for response_record in row.raw_ai_responses:
            text   = response_record.get("text", "")
            source = response_record.get("source", "heuristic")
            if not text or source == "google_ai_mode": 
                # Avoid re-scanning AI Mode JSON with regex (prone to error)
                continue

            extracted = extract_all(text)
            for field_name, (value, confidence) in extracted.items():
                if field_name in candidates:
                    candidates[field_name].append({
                        "value":      value,
                        "source":     source,
                        "confidence": confidence,
                    })

    # ── 3. For each field, pick winner and UPDATE instance attributes ──
    for field_name in ENRICHABLE_FIELDS:
        attr = FIELD_TO_ATTR.get(field_name, field_name)
        current_value = getattr(row, attr, None)

        # Skip if already exists in the original file
        if current_value and str(current_value).strip().lower() not in ("none", "nan", "", "null"):
            continue

        field_candidates = candidates[field_name]
        if not field_candidates:
            continue

        winner = best_value(field_candidates)
        new_value = winner.get("value")

        if new_value:
            # IMPORTANT: SET THE ATTRIBUTE SO IT'S SAVED IN THE FINAL EXCEL
            setattr(row, attr, new_value)
            row.enriched_fields[field_name] = {
                "value":      new_value,
                "source":     winner["source"],
                "confidence": round(winner["confidence"], 3),
                "was_empty":  True,
                "all_candidates": field_candidates,
            }
            logger.info(
                f"[Enricher] ✅ Row #{row.row_index} — Accepted '{field_name}': "
                f"'{new_value}' (conf={winner['confidence']:.2f}, source={winner['source']})"
            )
