#!/usr/bin/env python3
"""
Merge all DONE rows from SUCCEED, STD, and SIREN archive files into a single
unified part9_DONE_MERGED.xlsx.

Key findings:
- SUCCEED part9:       188 DONE rows (78 enriched cols)  ← original batch
- FAILED part9:         89 NO_TEL rows                    ← no phone found (legitimate)
- STD_2026-05-06:      662 rows from DIFFERENT batch       ← all AI_Phone populated
- SIREN_2026-05-06:    235 rows from DIFFERENT batch       ← all AI_Phone populated
- STD and SIREN have ZERO siren overlap with part9
=> 682 rows from original part9 remain unprocessed (interruption)
"""

import pandas as pd
from pathlib import Path

# ── Paths ─────────────────────────────────────────────────────────────────
SCRIPT_DIR = Path(__file__).parent
WORK_DIR   = SCRIPT_DIR.parent / "WORK"
OUT_DIR    = WORK_DIR / "ARCHIVE" / "SUCCEED"

SOURCES = {
    "SUCCEED": WORK_DIR / "ARCHIVE/SUCCEED/annuaire-des-entreprises-etablissements-030226_0405 MAJ 100426_part9_DONE.xlsx",
    "FAILED":  WORK_DIR / "ARCHIVE/FAILED/annuaire-des-entreprises-etablissements-030226_0405 MAJ 100426_part9_DONE.xlsx",
    "STD":     WORK_DIR / "ARCHIVE/STD/STD_2026-05-06.xlsx",
    "SIREN":   WORK_DIR / "ARCHIVE/SIREN/SIREN_2026-05-06.xlsx",
}

# ── Load & filter DONE ─────────────────────────────────────────────────────
print("Loading files...")
dfs = {}
for name, path in SOURCES.items():
    df = pd.read_excel(path)
    total = len(df)
    done  = df[df["Etat_IA"] == "DONE"]
    print(f"  {name:8s}: {total:4d} total, {len(done):4d} DONE")
    dfs[name] = done

succeed = dfs["SUCCEED"]
std     = dfs["STD"]
siren   = dfs["SIREN"]

# ── Deduplicate by siren ───────────────────────────────────────────────────
succeed_dedup = succeed.drop_duplicates(subset="siren", keep="first")
std_dedup     = std.drop_duplicates(subset="siren", keep="first")
siren_dedup   = siren.drop_duplicates(subset="siren", keep="first")

print(f"\nAfter siren dedup:")
print(f"  SUCCEED : {len(succeed_dedup)}")
print(f"  STD     : {len(std_dedup)}")
print(f"  SIREN   : {len(siren_dedup)}")

# ── Align column sets ──────────────────────────────────────────────────────
# SUCCEED has the full 78-col enriched schema.
# STD/SIREN have 67-col base schema (missing 14 enriched AI_ cols).
# Pad STD/SIREN with NaN for columns they lack.
suceed_cols = set(succeed.columns)

for col in suceed_cols - set(std.columns):
    std_dedup[col] = None

for col in suceed_cols - set(siren.columns):
    siren_dedup[col] = None

# Reorder to match SUCCEED column order
std_dedup   = std_dedup[succeed.columns]
siren_dedup = siren_dedup[succeed.columns]

# ── Merge ───────────────────────────────────────────────────────────────────
merged = pd.concat([succeed_dedup, std_dedup, siren_dedup], ignore_index=True)
merged = merged.drop_duplicates(subset="siren", keep="first")
merged = merged.sort_values("siren").reset_index(drop=True)

print(f"\nMerged file: {merged.shape[0]} rows × {merged.shape[1]} columns")
print(f"  SUCCEED origin : {sum(~merged['__fingerprint'].str.contains('SIREN', na=False))} rows")
print(f"  SIREN origin   : {sum(merged['__fingerprint'].str.contains('SIREN', na=False))} rows")

# ── Write ──────────────────────────────────────────────────────────────────
OUT_DIR.mkdir(parents=True, exist_ok=True)
out_path = OUT_DIR / "part9_DONE_MERGED.xlsx"
merged.to_excel(out_path, index=False)

print(f"\nWritten: {out_path}")
print(f"Shape: {merged.shape}")

# ── Summary stats ──────────────────────────────────────────────────────────
print("\n=== Merge Summary ===")
print(f"  SUCCEED part9  : {len(succeed_dedup)} DONE rows  (original batch)")
print(f"  STD batch      : {len(std_dedup)} DONE rows  (different company batch)")
print(f"  SIREN batch    : {len(siren_dedup)} DONE rows  (different company batch)")
print(f"  FAILED part9   : {len(dfs['FAILED'])} NO_TEL rows (legitimate — no phone found)")
print(f"  ─────────────────────────────────")
print(f"  TOTAL DONE     : {merged.shape[0]} unique sirenes")
print(f"  TOTAL NO_TEL   : {len(dfs['FAILED'])}")
print(f"  Original part9 : 1000 rows → {len(succeed_dedup)+len(dfs['FAILED'])} processed")
print(f"                     {1000 - (len(succeed_dedup)+len(dfs['FAILED']))} rows still unprocessed")
