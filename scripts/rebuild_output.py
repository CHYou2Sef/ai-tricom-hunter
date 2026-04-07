import os
import json
from pathlib import Path
# Ensure imports work
OUTPUT_DIR = Path(__file__).resolve().parent.parent / "output"
OUTPUT_ARCHIVE_DIR = OUTPUT_DIR / "Archived_Results"
OUTPUT_FAILED_DIR = OUTPUT_DIR / "Archived_Failed"

def reconstruct_from_json(json_file_path: Path):
    """
    Parses an _AUDIT.json file, reconstructs the correct Excel mapping,
    and drops the data into output/Archived_Results or output/Archived_Failed.
    Because the JSON has structured dictionaries, it is immune to the column slide bug.
    """
    print(f"🔄 Processing {json_file_path.name}...")
    try:
        with open(json_file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print(f"❌ Error loading JSON {json_file_path.name}: {e}")
        return

    if not data:
        print(f"⚠️ Empty JSON {json_file_path.name}")
        return

    success_rows = []
    failed_rows = []

    # Detect all enriched headers globally for this file
    enriched_keys = set()
    for row in data:
        enriched_keys.update(row.get("enriched_data", {}).keys())
    enriched_keys = sorted(list(enriched_keys))

    for row in data:
        original = row.get("original_data", {})
        phones = row.get("phones", {})
        enriched = row.get("enriched_data", {})
        
        status = row.get("status", "NO TEL")
        
        # Determine strict status
        if phones.get("main"):
            status = "Done"
        elif status == "NO TEL":
            status = "No Tel"
        elif status == "SKIP":
            status = "Skip"
        elif status == "DONE":
            status = "Done"
            
        row_dict = {}
        # 1. Original Data
        for k, v in original.items():
            row_dict[k] = v
            
        # 2. AI Phone Data
        row_dict["AI_Phone"] = phones.get("main", "")
        row_dict["AI_Agent_Phone"] = phones.get("agent", "")
        
        # 3. Handle Etat column gracefully 
        status_key = "Etat"
        row_dict[status_key] = status
        
        # 4. Enriched Data
        for k in enriched_keys:
            row_dict[f"AI_{k.upper()}"] = enriched.get(k, {}).get("value", "")

        if status == "Done":
            success_rows.append(row_dict)
        else:
            failed_rows.append(row_dict)

    import openpyxl
    from openpyxl import Workbook
    
    base_name = json_file_path.stem.replace("_AUDIT", "")
    # Remove bad prefixes (RETRY, DONE)
    import re
    clean_name = re.sub(r'^(RETRY_)+|(_DONE)+|(part\d+of\d+)+', '', base_name).strip("_")

    def save_rows(rows, target_dir, suffix):
        if not rows: return
        target_dir.mkdir(parents=True, exist_ok=True)
        out_path = target_dir / f"{clean_name}{suffix}.xlsx"
        
        # collect all keys dynamically
        headers = []
        for r in rows:
            for k in r.keys():
                if k not in headers:
                    headers.append(k)
        
        wb = Workbook()
        ws = wb.active
        ws.title = "Results"
        ws.append(headers)
        
        for r in rows:
            ws.append([r.get(h, "") for h in headers])
            
        wb.save(out_path)
        print(f"  ✅ Saved {len(rows)} rows to {out_path.parent.name}/{out_path.name}")

    if success_rows:
        save_rows(success_rows, OUTPUT_ARCHIVE_DIR, "")
        
    if failed_rows:
        save_rows(failed_rows, OUTPUT_FAILED_DIR, "_FAILED")

    # Move json to backup instead of deleting completely just in case
    backup_dir = OUTPUT_DIR / "_json_backup"
    backup_dir.mkdir(exist_ok=True)
    json_file_path.rename(backup_dir / json_file_path.name)
    
def main():
    print(f"🚀 Starting JSON to XLSX reconstruction in {OUTPUT_DIR}")
    
    found_any = False
    for root, dirs, files in os.walk(OUTPUT_DIR):
        if "_json_backup" in root:
            continue
        for file in files:
            if file.endswith("AUDIT.json") or file.endswith(".json"):
                found_any = True
                reconstruct_from_json(Path(root) / file)
                
    if not found_any:
        print("🤷 No JSON files found to convert.")
    else:
        print("🎉 Reconstruction complete!")

if __name__ == "__main__":
    main()
