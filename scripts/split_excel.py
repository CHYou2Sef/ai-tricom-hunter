#!/usr/bin/env python3
"""
Utility script to split large Excel files into smaller, more manageable parts.
Usage:
    python scripts/split_excel.py <path_to_excel_file> [chunk_size]

This avoids overwhelming the supervisor logic and simplifies memory usage when processing.
"""
import sys
import os
import argparse
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("Error: pandas is required to split Excel files. Please run inside the venv or install pandas.")
    sys.exit(1)

def split_excel(filepath: str, chunk_size: int = 500):
    path = Path(filepath)
    if not path.exists():
        print(f"Error: File '{filepath}' does not exist.")
        sys.exit(1)
        
    print(f"Reading {path}...")
    try:
        # Read with dtype=str to preserve phone numbers
        df = pd.read_excel(path, dtype=str)
    except Exception as e:
        print(f"Failed to read {path}: {e}")
        sys.exit(1)
        
    total_rows = len(df)
    print(f"Total rows: {total_rows}")
    
    if total_rows <= chunk_size:
        print(f"File is already smaller than or equal to {chunk_size} rows. No split needed.")
        return
        
    chunks = [df[i:i+chunk_size] for i in range(0, total_rows, chunk_size)]
    
    output_dir = path.parent
    base_name = path.stem
    ext = path.suffix
    
    for i, chunk in enumerate(chunks):
        out_path = output_dir / f"{base_name}_part{i+1}{ext}"
        print(f"Saving chunk {i+1}/{len(chunks)} ({len(chunk)} rows) to {out_path}")
        chunk.to_excel(out_path, index=False)
        
    print(f"\nSuccessfully split into {len(chunks)} parts.")
    
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Split large Excel files.")
    parser.add_argument("filepath", help="Path to the Excel file to split.")
    parser.add_argument("--chunk-size", "-c", type=int, default=500, help="Number of rows per split chunk.")
    
    args = parser.parse_args()
    split_excel(args.filepath, args.chunk_size)
