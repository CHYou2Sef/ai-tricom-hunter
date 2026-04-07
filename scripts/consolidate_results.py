#!/usr/bin/env python3
"""
scripts/consolidate_results.py

Collects all _AUDIT.json files from output/ and combines them 
into a single Master_Results.xlsx file.
Useful for finalizing a big batch processing.
"""

import os
import json
import glob
import pandas as pd
from pathlib import Path
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from excel.writer import save_subset_to_excel
from excel.reader import ExcelRow
from utils.logger import get_logger

logger = get_logger("Consolidator")

def consolidate():
    output_dir = Path("output")
    json_files = glob.glob(str(output_dir / "**" / "*_AUDIT.json"), recursive=True)
    
    if not json_files:
        logger.warning("No _AUDIT.json files found in output/.")
        return

    logger.info(f"🔍 Found {len(json_files)} audit files. Merging...")
    
    all_rows = []
    seen_identifiers = set() # Store SIREN or (NOM+ADR) to deduplicate
    
    for jf in json_files:
        try:
            with open(jf, "r", encoding="utf-8") as f:
                data = json.load(f)
                for record in data:
                    # We only care about DONE records for the final master
                    if record.get("status") != "DONE" and not record.get("phones", {}).get("main"):
                        continue
                    
                    # --- Deduplication Logic ---
                    raw = record.get("original_data", {})
                    siren = raw.get("siren") or raw.get("siret") or record.get("enriched_data", {}).get("siren", {}).get("value")
                    nom = raw.get("raison_sociale") or raw.get("nom")
                    adr = raw.get("adresse")
                    
                    identifier = None
                    if siren:
                        identifier = str(siren).strip().replace(" ", "")
                    elif nom:
                        identifier = f"{str(nom).strip().lower()}_{str(adr).strip().lower() if adr else ''}"
                    
                    if identifier:
                        if identifier in seen_identifiers:
                            continue # Skip duplicate
                        seen_identifiers.add(identifier)
                    # ---------------------------
                        
                    # Reconstruct an ExcelRow-like object for the writer
                    class MockRow:
                        def __init__(self, rec):
                            self.raw = rec.get("original_data", {})
                            self.phone = rec.get("phones", {}).get("main")
                            self.agent_phone = rec.get("phones", {}).get("agent")
                            self.status = rec.get("status")
                            self.enriched_fields = rec.get("enriched_data", {})
                            self.row_index = rec.get("row_index", 0)
                            
                    all_rows.append(MockRow(record))
        except Exception as e:
            logger.error(f"Failed to read {jf}: {e}")

    if not all_rows:
        logger.warning("No 'DONE' records found (or all were duplicates).")
        return

    logger.info(f"✅ Collected {len(all_rows)} successful leads.")
    
    master_path = output_dir / f"MASTER_CONSOLIDATED_{len(all_rows)}_LEADS.xlsx"
    save_subset_to_excel(all_rows, master_path)
    
    logger.info(f"🏆 Master Consolidated Excel created: {master_path}")
    print(f"\n✨ Success! Master file generated: {master_path}")

if __name__ == "__main__":
    consolidate()
