"""
╔══════════════════════════════════════════════════════════════════════════╗
║  utils/chunker.py                                                        ║
║                                                                          ║
║  Resilient file processing through decomposition.                        ║
║  If the agent crashes, it resumes from the exact chunk it left off.      ║
╚══════════════════════════════════════════════════════════════════════════╝
"""

import os
import json
import math
import csv
from typing import List, Any, Dict, Optional, Tuple
from pathlib import Path

import config
from excel.reader import read_excel, ExcelRow
from utils.logger import get_logger

logger = get_logger(__name__)

class FileChunker:
    """
    Handles splitting large datasets (Excel, CSV, JSON) into smaller chunks
    and tracks progress using a sidecar metadata file.
    """

    def __init__(self, work_dir: str = "input/chunks_processing"):
        self.work_dir = Path(work_dir)
        self.work_dir.mkdir(parents=True, exist_ok=True)

    def _get_metadata_path(self, original_file: Path) -> Path:
        """Returns the path to the sidecar metadata file."""
        return self.work_dir / f"{original_file.name}.meta.json"

    def split_file(self, file_path: str, chunk_size: int = config.DECOMPOSITION_CHUNK_SIZE) -> List[Path]:
        """
        Detects file type and splits it into smaller chunks.
        Supports: .xlsx, .xls, .csv, .json (as list)
        """
        p = Path(file_path)
        ext = p.suffix.lower()

        if ext == ".json":
            return self._split_json_list(p, chunk_size)
        elif ext in [".xlsx", ".xls", ".csv"]:
            return self._split_tabular(p, chunk_size)
        else:
            logger.warning(f"[Chunker] Unsupported extension: {ext}. Skipping chunking.")
            return [p]

    def _split_tabular(self, p: Path, chunk_size: int) -> List[Path]:
        """Splits CSV/Excel into smaller CSV chunks."""
        logger.info(f"[Chunker] Decomposing tabular file: {p.name}")
        
        try:
            # 1. Read the file using the project's native reader
            rows, mapping = read_excel(str(p))
            if not rows:
                return []

            total_records = len(rows)
            if total_records <= chunk_size:
                logger.info(f"[Chunker] {p.name} is small ({total_records} rows). No chunking needed.")
                return [p]

            num_chunks = math.ceil(total_records / chunk_size)
            chunk_paths = []

            # Get headers from the first row's raw data
            original_headers = list(rows[0].raw.keys())

            for i in range(num_chunks):
                start = i * chunk_size
                end = start + chunk_size
                chunk_data = rows[start:end]
                
                chunk_name = f"{p.stem}_batch_{i+1:03d}.csv"
                chunk_path = self.work_dir / chunk_name
                
                # Save as CSV for efficiency during the agent's run
                with open(chunk_path, 'w', encoding='utf-8-sig', newline='') as f:
                    writer = csv.DictWriter(f, fieldnames=original_headers, delimiter=';')
                    writer.writeheader()
                    for row in chunk_data:
                        # Only write the original columns to keep chunks 'clean'
                        writer.writerow(row.raw)
                
                chunk_paths.append(chunk_path)

            self._save_metadata(p, num_chunks, chunk_size)
            logger.info(f"[Chunker] Created {num_chunks} chunks for {p.name}")
            return chunk_paths
            
        except Exception as e:
            logger.error(f"[Chunker] Failed to split {p.name}: {e}", exc_info=True)
            return [p]

    def _split_json_list(self, p: Path, chunk_size: int) -> List[Path]:
        """Splits a JSON list into smaller JSON files."""
        logger.info(f"[Chunker] Decomposing JSON: {p.name}")
        
        with open(p, 'r', encoding='utf-8') as f:
            data = json.load(f)

        if not isinstance(data, list):
            logger.warning("[Chunker] JSON is not a list. Skipping.")
            return [p]

        total_records = len(data)
        num_chunks = math.ceil(total_records / chunk_size)
        chunk_paths = []

        for i in range(num_chunks):
            start = i * chunk_size
            end = start + chunk_size
            chunk_data = data[start:end]
            
            chunk_name = f"{p.stem}_batch_{i+1:03d}.json"
            chunk_path = self.work_dir / chunk_name
            
            with open(chunk_path, 'w', encoding='utf-8') as f:
                json.dump(chunk_data, f, indent=2, ensure_ascii=False)
            
            chunk_paths.append(chunk_path)

        self._save_metadata(p, num_chunks, chunk_size)
        return chunk_paths

    def _save_metadata(self, original_file: Path, total_chunks: int, chunk_size: int):
        metadata = {
            "original_file": str(original_file.absolute()),
            "total_chunks": total_chunks,
            "completed_chunks": [],
            "current_chunk_index": 0,
            "chunk_size": chunk_size,
            "status": "in_progress",
            "last_updated": Path(original_file).stat().st_mtime
        }
        with open(self._get_metadata_path(original_file), 'w') as f:
            json.dump(metadata, f, indent=4)

    def mark_chunk_done(self, original_file: Path, chunk_index: int):
        """Marks a chunk as finished in the sidecar metadata."""
        meta_path = self._get_metadata_path(original_file)
        if not meta_path.exists():
            return

        with open(meta_path, 'r') as f:
            meta = json.load(f)

        if chunk_index not in meta["completed_chunks"]:
            meta["completed_chunks"].append(chunk_index)
            meta["completed_chunks"].sort()
        
        # Next index is the first one not completed
        for i in range(meta["total_chunks"]):
            if i not in meta["completed_chunks"]:
                meta["current_chunk_index"] = i
                break
        else:
            meta["status"] = "completed"
            meta["current_chunk_index"] = meta["total_chunks"]

        with open(meta_path, 'w') as f:
            json.dump(meta, f, indent=4)

    def get_next_pending_chunk(self, original_file: Path) -> int:
        """Returns the index of the next chunk to be processed."""
        meta_path = self._get_metadata_path(original_file)
        if not meta_path.exists():
            return 0
        with open(meta_path, 'r') as f:
            meta = json.load(f)
        return meta.get("current_chunk_index", 0)

    def is_file_completed(self, original_file: Path) -> bool:
        """Checks if all chunks for this file are done."""
        meta_path = self._get_metadata_path(original_file)
        if not meta_path.exists():
            return False
        with open(meta_path, 'r') as f:
            meta = json.load(f)
        return meta["status"] == "completed"

    def recover_incomplete_work(self) -> Dict[str, int]:
        """
        Scans the chunks directory for incomplete meta files and returns them.
        """
        incomplete = {}
        for meta_file in self.work_dir.glob("*.meta.json"):
            with open(meta_file, 'r') as f:
                meta = json.load(f)
            
            if meta["status"] != "completed":
                incomplete[meta["original_file"]] = meta["current_chunk_index"]
        
        return incomplete

# Example usage for GEMINI.md
if __name__ == "__main__":
    chunker = FileChunker()
    # chunker.split_json_list("input/large_data.json")
