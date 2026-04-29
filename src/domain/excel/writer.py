"""
╔══════════════════════════════════════════════════════════════════════════╗
║  domain/excel/writer.py                                                  ║
║                                                                          ║
║  Professional Excel/CSV Output Generator                                 ║
║                                                                          ║
║  ROLE:                                                                   ║
║    Saves processed rows to beautifully formatted Excel files with        ║
║    color-coded AI columns, auto-filters, and frozen panes.               ║
║                                                                          ║
║  HOW IT WORKS:                                                           ║
║    1. save_subset_to_excel() writes rows with professional formatting   ║
║    2. save_results() updates BOTH the working file AND a daily fusion    ║
║    3. Daily fusion deduplicates by fingerprint + phone (one-to-many)     ║
║    4. Drops internal __columns from final output                         ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import datetime
import pandas as pd
import numpy as np
from pathlib import Path
from typing import List, Dict, Any
from core import config
from core.logger import get_logger
from common.fs import safe_mkdir, safe_touch
from domain.json.jsonl_handler import JSONLWriter, JSONLReader

logger = get_logger(__name__)

def _apply_pro_formatting(writer, df, rows: List, sheet_name="Results"):
    """Apply professional XlsxWriter formatting to the output."""
    workbook  = writer.book
    worksheet = writer.sheets[sheet_name]

    # --- 1. Formats ---
    header_fmt = workbook.add_format({
        'bold': True,
        'text_wrap': False,
        'valign': 'top',
        'fg_color': '#2F5597',  # Dark Blue
        'font_color': 'white',
        'border': 1
    })

    ai_col_fmt = workbook.add_format({
        'bg_color': '#DDEBF7',  # Light Blue
        'border': 1
    })

    filled_fmt = workbook.add_format({
        'bg_color': '#E2EFDA',  # Light Green (Filled from Empty)
        'border': 1
    })

    clone_fmt = workbook.add_format({
        'bg_color': '#FFF2CC',  # Light Yellow (New Row/Clone)
        'border': 1
    })

    # --- 2. Freeze Panes (Header row) ---
    worksheet.freeze_panes(1, 0)

    # --- 3. Auto-Filter ---
    worksheet.autofilter(0, 0, len(df), len(df.columns) - 1)

    # --- 4. Column Widths & Header Style ---
    for i, col_name in enumerate(df.columns):
        # Handle duplicate column names: df.iloc[:, i] ensures we get a single Series
        col_data = df.iloc[:, i]
        
        try:
            # Flatten data to strings and find max length
            max_data_len = col_data.astype(str).map(len).max()
            if pd.isna(max_data_len): max_data_len = 0
        except:
            max_data_len = 0
            
        max_len = max(float(max_data_len), len(str(col_name))) + 2
        width = min(max_len, 50)
        
        # Write header with format
        worksheet.write(0, i, str(col_name), header_fmt)

    # --- 5. Conditional Row/Cell Highlighting ---
    for row_idx in range(len(df)):
        row_num = row_idx + 1  # Offset by 1 for headers
        
        # Get the original ExcelRow object if available for deep inspection (filled_fmt, is_clone)
        excel_row = rows[row_idx] if row_idx < len(rows) else None
        is_clone = getattr(excel_row, 'is_clone', False) if excel_row else False
        
        for col_idx, col_name in enumerate(df.columns):
            # Check if this specific field was enriched from an EMPTY state
            is_filled = False
            if excel_row:
                # Map column name back to enricher field keys
                field_key = str(col_name).replace("AI_", "").lower()
                if field_key in excel_row.enriched_fields:
                    if excel_row.enriched_fields[field_key].get("was_empty"):
                        is_filled = True
            
            # Special case: Status column highlights
            if col_name == config.STATUS_COLUMN_NAME:
                val = str(df.iloc[row_idx, col_idx]).upper()
                if val == "DONE":
                    worksheet.write(row_num, col_idx, val, ai_col_fmt)
                    continue
                elif val == "LOW_CONF":
                    worksheet.write(row_num, col_idx, val, clone_fmt)
                    continue
                elif "NO" in val and "TEL" in val:
                    # Light formatting for NO TEL too? Optional, but keeps it clean
                    worksheet.write(row_num, col_idx, val, ai_col_fmt)
                    continue

            # Apply formatting
            target_fmt = None
            if is_filled:
                target_fmt = filled_fmt
            elif is_clone:
                target_fmt = clone_fmt
            elif str(col_name).startswith("AI_"):
                # All columns added by AI (Phone, Email, Score, Latency...) get light blue
                target_fmt = ai_col_fmt
                
            if target_fmt:
                val = df.iloc[row_idx, col_idx]
                # Handle NaNs for Excel
                if pd.isna(val): val = ""
                worksheet.write(row_num, col_idx, val, target_fmt)

def _deduplicate_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Ensure all column names are unique, keeping the last occurrence (the newest data)."""
    if df.columns.duplicated().any():
        # Logic: ~df.columns.duplicated(keep='last') returns True for the last occurrence
        # and for unique columns.
        df = df.loc[:, ~df.columns.duplicated(keep='last')]
    return df

def save_subset_to_excel(rows: list, target_path: Path) -> None:
    """Save a list of ExcelRow objects using Pandas with Pro formatting."""
    if not rows: return
    
    # 1. Prepare Data
    data = [r.to_dict() if hasattr(r, 'to_dict') else r for r in rows]
    df = pd.DataFrame(data)
    
    # Reorder/Rename status header to user's config
    if "__status" in df.columns:
        df = df.rename(columns={
            "__status": config.STATUS_COLUMN_NAME, 
            "__phone": "AI_Phone", 
            "__agent_phone": "AI_Agent_Phone"
        })
    
    # 2. Drop technical internal columns (starting with __)
    internal_cols = [c for c in df.columns if str(c).startswith("__") and c != "__fingerprint"]
    if internal_cols:
        df = df.drop(columns=internal_cols)
    
    # 3. Protection against duplicate columns
    df = _deduplicate_columns(df)

    safe_mkdir(target_path.parent)
    suffix = target_path.suffix.lower()

    if suffix == ".csv":
        df.to_csv(target_path, sep=";", index=False, encoding="utf-8-sig")
        logger.info(f"[Writer] Subset saved as CSV: {target_path}")
    else:
        with pd.ExcelWriter(target_path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Results", index=False)
            _apply_pro_formatting(writer, df, rows)
        logger.info(f"[Writer] Subset saved as Pro Excel: {target_path}")
    
    safe_touch(target_path)

def save_jsonl_to_excel(jsonl_path: Path, excel_path: Path) -> None:
    """Post-processing: Convert a JSONL stream to a formatted Excel file."""
    reader = JSONLReader(str(jsonl_path))
    rows = reader.get_all_rows()
    if not rows:
        logger.warning(f"[Writer] No data in {jsonl_path} to convert to Excel.")
        return
    save_subset_to_excel(rows, excel_path)

def save_results(rows: list, original_filepath: str, force: bool = False) -> None:
    """Daily Fusion Handler + Local File Synchronizer."""
    if not rows: return
    
    orig_path = Path(original_filepath)
    
    # ── Part A: Save back to the ORIGINAL WORKING FILE ──
    # [Phase 2] We now skip the heavy Excel rewrite during the loop.
    # The real persistence is handled by FileProgressTracker (JSON).
    # We only update the local Excel if it's a small file or at the very end (force=True).
    if force or len(rows) < 50:
        try:
            save_subset_to_excel(rows, orig_path)
        except Exception as e:
            logger.error(f"[Writer] Failed to update local worker file {orig_path.name}: {e}")
    else:
        logger.debug(f"[Writer] Skipping mid-loop Excel save for large file ({len(rows)} rows).")

    # ── Part B: Daily Fusion Handler ──
    input_folder = orig_path.parent.name
    out_dir = config.get_output_dir(input_folder)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    fusion_path = out_dir / f"{input_folder}_{date_str}.xlsx"

    # 1. Convert new rows to DF (Only include ENRICHED rows in Fusion file)
    new_data = []
    for r in rows:
        # DONE = confirmed data. LOW_CONF = SIREN mismatch — include for operator review.
        if r.status not in ("DONE", "LOW_CONF"):
            continue
            
        d = r.to_dict()
        d["__fingerprint"] = r.get_fingerprint()
        new_data.append(d)
    
    if not new_data:
        logger.info("[Writer] No new enriched rows to add to fusion file.")
        return
        
    new_df = pd.DataFrame(new_data)
    
    # Standardize column names
    new_df = new_df.rename(columns={
        "__status": config.STATUS_COLUMN_NAME, 
        "__phone": "AI_Phone", 
        "__agent_phone": "AI_Agent_Phone"
    })
    
    # Deduplicate columns in new_df
    new_df = _deduplicate_columns(new_df)

    # 2. Merge with existing if available
    if fusion_path.exists():
        try:
            old_df = pd.read_excel(fusion_path, dtype=str)
            
            # Combine and deduplicate rows by (fingerprint + phone) to allow one-to-many
            final_df = pd.concat([old_df, new_df], ignore_index=True, sort=False)
            if "__fingerprint" in final_df.columns and "AI_Phone" in final_df.columns:
                final_df = final_df.drop_duplicates(subset=["__fingerprint", "AI_Phone"], keep='last')
            
            # Final protection for columns
            final_df = _deduplicate_columns(final_df)
            final_df = final_df.reset_index(drop=True)
        except Exception as e:
            logger.error(f"[Writer] Failed to fuse with existing file: {e}. Starting fresh.")
            final_df = new_df
    else:
        final_df = new_df

    # 3. Final Save with Pro Formatting
    try:
        with pd.ExcelWriter(fusion_path, engine='xlsxwriter') as writer:
            final_df.to_excel(writer, sheet_name="Results", index=False)
            # Re-read rows matching the final_df logic if needed, but for simplicity
            # we pass a placeholder or we use the data we have.
            # NOTE: Daily fusion doesn't have the original 'rows' objects anymore 
            # for the entire file, but for the 'new_data' it does.
            # To keep it perfect, we use the original objects for the whole df.
            # However, for now, we'll just apply standard formatting to the fusion file.
            _apply_pro_formatting(writer, final_df, []) # No individual highlighting in fusion for now
        safe_touch(fusion_path)
        logger.info(f"[Writer] Daily fusion updated: {fusion_path.name}")
    except Exception as e:
        logger.error(f"[Writer] Critical failure during fusion save: {e}")
