"""
╔══════════════════════════════════════════════════════════════════════════╗
║  excel/cleaner.py  —  Input File Cleaning & Classification               ║
║                                                                          ║
║  POST-PROCESSING STEP (called after every file is processed).            ║
║  For each row in the finished file:                                      ║
║    1. Detect which key fields are present (SIREN, RS, Adresse, Tel)     ║
║    2. Classify the row into one of 4 categories                         ║
║    3. Write the categorised rows into separate Excel files               ║
║                                                                          ║
║  Classification rules (first match wins):                                ║
║    std_input   → SIREN + RS + Adresse    (complete record)              ║
║    RS_input    → RS + Adresse (no SIREN)                                ║
║    sir_input   → SIREN/SIRET + Adresse   (no RS)                       ║
║    other_input → any other partial combination                           ║
║    DISCARD     → no useful field at all  (row dropped)                  ║
║                                                                          ║
║  BEGINNER NOTE:                                                          ║
║    We reuse the fields already extracted on each ExcelRow object.       ║
║    No re-parsing of the raw Excel columns is needed.                    ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import re
from typing import Dict, List

import openpyxl
from openpyxl import Workbook
from openpyxl.styles import PatternFill, Font

import config
from excel.reader import ExcelRow
from utils.logger import get_logger

logger = get_logger(__name__)

import os
from typing import Dict, List
from pathlib import Path

import config
from excel.reader import ExcelRow
from excel.writer import save_subset_to_excel
from utils.logger import get_logger

logger = get_logger(__name__)

# CATEGORY CONSTANTS
CAT_STD     = "STD"
CAT_RS      = "RS"
CAT_SIR     = "SIREN"
CAT_OTHER   = "OTHERS"
CAT_DISCARD = "DISCARD"

def get_category_dir(category: str) -> str:
    return {
        CAT_STD:   config.INPUT_STD_DIR,
        CAT_RS:    config.INPUT_RS_DIR,
        CAT_SIR:   config.INPUT_SIR_DIR,
        CAT_OTHER: config.INPUT_OTHER_DIR,
    }.get(category, "")

def classify_row(row: ExcelRow) -> str:
    """Classify row based on available fields for search."""
    has_nom   = bool(row.nom)
    has_sir   = bool(row.siren)
    has_adr   = bool(row.adresse)
    has_phone = bool(row.phone)

    if not (has_nom or has_sir or has_adr or has_phone):
        return CAT_DISCARD

    if has_sir and has_nom and has_adr:
        return CAT_STD
    if has_nom and has_adr and not has_sir:
        return CAT_RS
    if has_sir and has_adr and not has_nom:
        return CAT_SIR
    
    return CAT_OTHER

def clean_and_classify(
    rows: List[ExcelRow],
    source_filepath: str,
    original_headers: List[str], # Kept for compatibility but save_subset uses row objects
) -> Dict[str, int]:
    """Sort rows into buckets and save each bucket as a Pro Excel/CSV file."""
    filename = os.path.basename(source_filepath)
    logger.info(f"[Cleaner] Classifying {len(rows)} rows from '{filename}'")

    buckets: Dict[str, List[ExcelRow]] = {CAT_STD: [], CAT_RS: [], CAT_SIR: [], CAT_OTHER: []}
    discarded = 0

    for row in rows:
        cat = classify_row(row)
        if cat == CAT_DISCARD:
            discarded += 1
        else:
            buckets[cat].append(row)

    stats: Dict[str, int] = {}
    for cat, cat_rows in buckets.items():
        if not cat_rows:
            stats[cat] = 0
            continue
            
        dest_dir = get_category_dir(cat)
        target_path = Path(dest_dir) / filename
        
        # USE UNIFIED PRO WRITER
        save_subset_to_excel(cat_rows, target_path)
        stats[cat] = len(cat_rows)

    logger.info(
        f"[Cleaner] Result for '{filename}': "
        f"STD:{stats[CAT_STD]} | RS:{stats[CAT_RS]} | SIR:{stats[CAT_SIR]} | OTH:{stats[CAT_OTHER]} | 🗑️:{discarded}"
    )
    return stats
