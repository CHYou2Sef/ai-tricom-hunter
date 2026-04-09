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

# ──────────────────────────────────────────────────────────────────────────────
# CATEGORY CONSTANTS
# ──────────────────────────────────────────────────────────────────────────────

CAT_STD    = "std_input"    # SIREN + RS + Adresse  (complete)
CAT_RS     = "RS_input"     # RS + Adresse  (no SIREN)
CAT_SIR    = "sir_input"    # SIREN/SIRET + Adresse  (no RS)
CAT_OTHER  = "other_input"  # partial / unclassified
CAT_DISCARD = "DISCARD"     # no useful data → row dropped

def get_category_dir(category: str) -> str:
    """Return the output directory for a given category (from config)."""
    return {
        CAT_STD:   config.INPUT_STD_DIR,
        CAT_RS:    config.INPUT_RS_DIR,
        CAT_SIR:   config.INPUT_SIR_DIR,
        CAT_OTHER: config.INPUT_OTHER_DIR,
    }.get(category, "")

# ──────────────────────────────────────────────────────────────────────────────
# ROW CLASSIFICATION
# ──────────────────────────────────────────────────────────────────────────────

def classify_row(row: ExcelRow) -> str:
    """
    Determine the category of a single ExcelRow based on which key
    fields are available.

    Decision table (first match wins):
    ┌──────────────────────────────────────┬─────────────────┐
    │ Condition                            │ Category        │
    ├──────────────────────────────────────┼─────────────────┤
    │ SIREN + RS + Adresse                 │ std_input       │
    │ RS + Adresse  (no SIREN)             │ RS_input        │
    │ SIREN/SIRET + Adresse  (no RS)       │ sir_input       │
    │ At least ONE field present           │ other_input     │
    │ Nothing at all                       │ DISCARD         │
    └──────────────────────────────────────┴─────────────────┘

    Args:
        row : An ExcelRow (fields already parsed by reader.py)

    Returns:
        One of: CAT_STD, CAT_RS, CAT_SIR, CAT_OTHER, CAT_DISCARD
    """
    has_nom  = _has_nom(row)
    has_sir  = _has_siren(row)
    has_adr  = _has_adresse(row)
    has_tel  = _has_telephone(row)

    if not (has_nom or has_sir or has_adr or has_tel):
        return CAT_DISCARD

    # ── If we have a phone AND (Name or Address or SIREN), it's already "DONE" ──
    if has_tel and (has_nom or has_adr or has_sir):
        # We can mark it here, or later when writing. 
        # For classification, it's still a complete record (STD) or partial.
        # But user wants us to add a "DONE" column.
        logger.info(
                f"[DONE] Row #{row.row_index} has a phone number and (Name or Address or SIREN)"
            )

    # ── Priority matching ──
    if has_sir and has_nom and has_adr:
        return CAT_STD

    if has_nom and has_adr and not has_sir:
        return CAT_RS

    if has_sir and has_adr and not has_nom:
        return CAT_SIR

    # Everything else: partial data — keep but classify as "other"
    return CAT_OTHER


def _has_nom(row: ExcelRow) -> bool:
    """Check for company name aliases."""
    aliases = ["nom", "name", "dénomination", "raison sociale", "entreprise", "société", "commercial", "nom commercial", "rs"]
    for col_name, value in row.raw.items():
        if value is None: continue
        col_lower = str(col_name).lower()
        if any(a in col_lower for a in aliases):
            val_str = str(value).strip()
            if val_str and val_str.lower() not in ("none", "nan", ""):
                return True
    return False


def _has_siren(row: ExcelRow) -> bool:
    """Check for SIREN/SIRET aliases."""
    aliases = ["siren", "siret", "identifiant"]
    for col_name, value in row.raw.items():
        if value is None: continue
        col_lower = str(col_name).lower()
        if any(a in col_lower for a in aliases):
            val_str = str(value).strip()
            # SIREN is 9 digits, SIRET is 14
            if re.search(r'\d{9}', val_str):
                return True
    return False


def _has_adresse(row: ExcelRow) -> bool:
    """Check for address aliases."""
    aliases = ["adresse", "address", "siège", "localisation", "lieu", "adresse du siège", "adr"]
    for col_name, value in row.raw.items():
        if value is None: continue
        col_lower = str(col_name).lower()
        if any(a in col_lower for a in aliases):
            val_str = str(value).strip()
            if val_str and val_str.lower() not in ("none", "nan", ""):
                return True
    return False


def _has_telephone(row: ExcelRow) -> bool:
    """
    Check whether any column in the raw row data looks like a phone field.
    We scan column *names* for telephone-related keywords.

    This is used only for the DISCARD decision so we don't accidentally
    throw away rows that only have a phone number.
    """
    tel_keywords = ["tel", "telephone", "téléphone", "mobile", "fax", "portable", "phone"]
    for col_name, value in row.raw.items():
        if value is None:
            continue
        col_lower = str(col_name).lower()
        if any(kw in col_lower for kw in tel_keywords):
            val_str = str(value).strip()
            if val_str and val_str.lower() not in ("none", "nan", ""):
                return True
    return False


# ──────────────────────────────────────────────────────────────────────────────
# EXCEL WRITER HELPER
# ──────────────────────────────────────────────────────────────────────────────

# Colour palette for each category header row
_HEADER_FILLS = {
    CAT_STD:   PatternFill("solid", fgColor="1E8449"),  # dark green
    CAT_RS:    PatternFill("solid", fgColor="1A5276"),  # dark blue
    CAT_SIR:   PatternFill("solid", fgColor="7D6608"),  # dark amber
    CAT_OTHER: PatternFill("solid", fgColor="6D3A3A"),  # dark red
}


def _write_category_file(
    category: str,
    rows: List[ExcelRow],
    original_headers: List[str],
    dest_dir: str,
    filename: str,
) -> None:
    """
    Write a subset of rows into a new Excel file at dest_dir/filename.

    Args:
        category         : Category label (used for header colour)
        rows             : List of ExcelRow objects belonging to this category
        original_headers : Column names from the source file
        dest_dir         : Target directory (already exists)
        filename         : Output file name (same as input file)
    """
    if not rows:
        return

    dest_path = os.path.join(dest_dir, filename)
    wb = Workbook()
    ws = wb.active
    ws.title = category

    header_fill = _HEADER_FILLS.get(category, PatternFill("solid", fgColor="444444"))
    header_font = Font(bold=True, color="FFFFFF")

    # ── Update headers with Agent Status ──
    out_headers = list(original_headers)
    status_col = config.STATUS_COLUMN_NAME
    if status_col not in out_headers:
        out_headers.append(status_col)
    
    # ── Write header row ──
    # ws.append(out_headers)
    for cell in ws[1]:
        cell.fill = header_fill
        cell.font = header_font

    # ── Write data rows ──
    for row in rows:
        # Determine "Etat" value
        has_tel = _has_telephone(row)
        has_nom = _has_nom(row)
        has_adr = _has_adresse(row)
        has_sir = _has_siren(row)
        
        etat = "DONE" if (has_tel and (has_nom or has_adr or has_sir)) else "PENDING"
        
        # ⭐ BUG FIX: Map data row using out_headers to avoid column shift
        data_row = []
        status_col = config.STATUS_COLUMN_NAME
        for h in out_headers:
            if h == status_col:
                data_row.append(etat)
            else:
                data_row.append(row.raw.get(h, ""))

        ws.append(data_row)

    wb.save(dest_path)
    logger.info(
        f"[Cleaner] ✅ {category}: {len(rows)} row(s) → {dest_path}"
    )


# ──────────────────────────────────────────────────────────────────────────────
# PUBLIC API
# ──────────────────────────────────────────────────────────────────────────────

def clean_and_classify(
    rows: List[ExcelRow],
    source_filepath: str,
    original_headers: List[str],
) -> Dict[str, int]:
    """
    Main entry point.

    Classifies every row in `rows`, discards empty rows, and writes one
    output file per non-empty category into the corresponding sub-folder.

    Args:
        rows             : All ExcelRow objects from the processed file
        source_filepath  : Path to the original source .xlsx file
        original_headers : Column names from the source file (in order)

    Returns:
        A dict mapping category name → number of rows written
        e.g. {"std_input": 45, "RS_input": 12, "sir_input": 3, "other_input": 7}
    """
    filename = os.path.basename(source_filepath)
    # Ensure the output is always saved with an .xlsx extension, even if the input was a temporary .csv chunk
    if not filename.lower().endswith(".xlsx"):
        filename = os.path.splitext(filename)[0] + ".xlsx"

    logger.info(f"[Cleaner] ━━━ Classifying {len(rows)} rows from '{filename}' ━━━")

    # ── Group rows by category ──
    buckets: Dict[str, List[ExcelRow]] = {
        CAT_STD:   [],
        CAT_RS:    [],
        CAT_SIR:   [],
        CAT_OTHER: [],
    }
    discarded = 0

    for row in rows:
        cat = classify_row(row)
        if cat == CAT_DISCARD:
            discarded += 1
            logger.debug(
                f"[Cleaner] Row #{row.row_index} DISCARDED — no useful fields."
            )
        else:
            buckets[cat].append(row)

    # ── Write one file per non-empty category ──
    stats: Dict[str, int] = {}
    for cat, cat_rows in buckets.items():
        dest_dir = get_category_dir(cat)
        _write_category_file(
            category=cat,
            rows=cat_rows,
            original_headers=original_headers,
            dest_dir=dest_dir,
            filename=filename,
        )
        stats[cat] = len(cat_rows)

    # ── Summary log ──
    logger.info(
        f"[Cleaner] ━━━ Classification done for '{filename}' ━━━\n"
        f"         📦 std_input   : {stats[CAT_STD]}\n"
        f"         📋 RS_input    : {stats[CAT_RS]}\n"
        f"         🔢 sir_input   : {stats[CAT_SIR]}\n"
        f"         📁 other_input : {stats[CAT_OTHER]}\n"
        f"         🗑️  discarded   : {discarded}"
    )

    return stats
