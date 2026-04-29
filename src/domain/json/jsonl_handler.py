"""
╔══════════════════════════════════════════════════════════════════════════╗
║  domain/json/jsonl_handler.py                                             ║
║                                                                          ║
║  Role: Streaming IO for massive datasets using JSON Lines (.jsonl).      ║
║  Enables horizontal scaling and memory-independent processing.           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import json
import os
from typing import Iterator, Dict, Any, List, Optional
from pathlib import Path
from core.logger import get_logger

logger = get_logger(__name__)

class JSONLWriter:
    """Append-only JSONL writer for real-time persistence."""
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)
        # Ensure parent exists
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def write_row(self, data: Dict[str, Any]):
        """Append a single row to the file."""
        with open(self.filepath, "a", encoding="utf-8") as f:
            f.write(json.dumps(data, ensure_ascii=False) + "\n")

    def write_batch(self, rows: List[Dict[str, Any]]):
        """Append multiple rows at once."""
        with open(self.filepath, "a", encoding="utf-8") as f:
            for row in rows:
                f.write(json.dumps(row, ensure_ascii=False) + "\n")

class JSONLReader:
    """Generator-based JSONL reader for low memory footprint."""
    def __init__(self, filepath: str):
        self.filepath = Path(filepath)

    def stream_rows(self) -> Iterator[Dict[str, Any]]:
        """Yield rows one by one."""
        if not self.filepath.exists():
            logger.warning(f"[JSONLReader] File not found: {self.filepath}")
            return

        with open(self.filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as e:
                    logger.error(f"[JSONLReader] Decode error in {self.filepath}: {e}")
                    continue

    def get_all_rows(self) -> List[Dict[str, Any]]:
        """Convenience method for smaller files."""
        return list(self.stream_rows())

def convert_excel_to_jsonl(excel_path: str, jsonl_path: str):
    """Utility to convert original input to streaming format."""
    import pandas as pd
    logger.info(f"[JSONL] Converting {excel_path} to streaming JSONL...")
    df = pd.read_excel(excel_path, dtype=str)
    writer = JSONLWriter(jsonl_path)
    # Convert to dicts and write
    rows = df.to_dict(orient="records")
    writer.write_batch(rows)
    logger.info(f"✅ [JSONL] Conversion complete: {len(rows)} rows.")
