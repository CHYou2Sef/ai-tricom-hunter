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
from typing import List
from core import config
from core.logger import get_logger
from common.fs import safe_mkdir, safe_touch

logger = get_logger(__name__)

def _apply_pro_formatting(writer, df, sheet_name="Results"):
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
        
        # Apply special color if it's an AI column
        if str(col_name).startswith("AI_") or str(col_name) == config.STATUS_COLUMN_NAME:
            worksheet.set_column(i, i, width, ai_col_fmt)
        else:
            worksheet.set_column(i, i, width)
        
        # Write header with format
        worksheet.write(0, i, str(col_name), header_fmt)

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
    data = [r.to_dict() for r in rows]
    df = pd.DataFrame(data)
    
    # Reorder/Rename status header to user's config
    if "__status" in df.columns:
        df = df.rename(columns={
            "__status": config.STATUS_COLUMN_NAME, 
            "__phone": "AI_Phone", 
            "__agent_phone": "AI_Agent_Phone"
        })
    
    # 2. Drop technical internal columns (starting with __)
    # These are kept in JSON checkpoints but removed from final Excel/CSV reports.
    internal_cols = [c for c in df.columns if str(c).startswith("__")]
    if internal_cols:
        df = df.drop(columns=internal_cols)
    
    # 3. Protection against duplicate columns
    df = _deduplicate_columns(df)

    safe_mkdir(target_path.parent)
    suffix = target_path.suffix.lower()

    if suffix == ".csv":
        # Professional CSV: UTF-8-SIG (Excel friendly) + Semicolon
        df.to_csv(target_path, sep=";", index=False, encoding="utf-8-sig")
        logger.info(f"[Writer] Subset saved as CSV (Pandas): {target_path}")
    else:
        # Professional Excel: XlsxWriter engine
        with pd.ExcelWriter(target_path, engine='xlsxwriter') as writer:
            df.to_excel(writer, sheet_name="Results", index=False)
            _apply_pro_formatting(writer, df)
        logger.info(f"[Writer] Subset saved as Pro Excel (Pandas): {target_path}")
    
    safe_touch(target_path)

def save_results(rows: list, original_filepath: str) -> None:
    """Daily Fusion Handler + Local File Synchronizer."""
    if not rows: return
    
    orig_path = Path(original_filepath)
    
    # ── Part A: Save back to the ORIGINAL WORKING FILE ──
    # This keeps the current batch file updated in real-time.
    try:
        save_subset_to_excel(rows, orig_path)
    except Exception as e:
        logger.error(f"[Writer] Failed to update local worker file {orig_path.name}: {e}")

    # ── Part B: Daily Fusion Handler ──
    input_folder = orig_path.parent.name
    out_dir = config.get_output_dir(input_folder)
    date_str = datetime.date.today().strftime("%Y-%m-%d")
    fusion_path = out_dir / f"{input_folder}_{date_str}.xlsx"

    # 1. Convert new rows to DF (Only include ENRICHED rows in Fusion file)
    new_data = []
    for r in rows:
        if r.status != "DONE":
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
            _apply_pro_formatting(writer, final_df)
        safe_touch(fusion_path)
        logger.info(f"[Writer] Daily fusion updated: {fusion_path.name}")
    except Exception as e:
        logger.error(f"[Writer] Critical failure during fusion save: {e}")
