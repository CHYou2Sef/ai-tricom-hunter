import json
import os
from pathlib import Path
from typing import Dict, Any, Optional

from core import config
from core.logger import get_logger

logger = get_logger(__name__)

class FileProgressTracker:
    """
    Persistent state tracker for a SPECIFIC file.
    Saves results row-by-row into a JSON file for crash recovery.
    """

    def __init__(self, original_filepath: str):
        self.original_path = Path(original_filepath)
        # Checkpoint name: File_Name.xlsx -> File_Name.xlsx.json
        self.checkpoint_path = config.CHECKPOINTS_DIR / f"{self.original_path.name}.json"
        self.data: Dict[str, Any] = {} # row_index (str) -> {phone, agent_phone, status, etc}
        self.load()

    def load(self):
        """Load the checkpoint if it exists."""
        if self.checkpoint_path.exists():
            try:
                with open(self.checkpoint_path, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                logger.info(f"[Progress] Loaded {len(self.data)} rows from checkpoint: {self.checkpoint_path.name}")
            except Exception as e:
                logger.warning(f"[Progress] Failed to load checkpoint {self.checkpoint_path.name}: {e}")
                self.data = {}
        else:
            self.data = {}

    def save(self):
        """Save current state to JSON."""
        try:
            with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Progress] Failed to save checkpoint: {e}")

    def mark_row_done(self, row_index: int, phone: Optional[str], agent_phone: Optional[str], status: str, extra: dict = None):
        """Record the full result for a row."""
        entry = {
            "phone": phone,
            "agent_phone": agent_phone,
            "status": status,
        }
        if extra:
            entry.update(extra)
        
        self.data[str(row_index)] = entry
        self.save()

    def get_row_data(self, row_index: int) -> Optional[dict]:
        """Retrieve cached data for a row."""
        return self.data.get(str(row_index))

    def is_row_done(self, row_index: int) -> bool:
        """Check if a row is already recorded in checkpoint."""
        return str(row_index) in self.data

    def delete(self):
        """Remove the checkpoint file (cleanup after final export)."""
        if self.checkpoint_path.exists():
            try:
                os.remove(self.checkpoint_path)
            except Exception as e:
                logger.error(f"[Progress] Cleanup failed for {self.checkpoint_path.name}: {e}")

    def archive(self):
        """Move the checkpoint to the archived_json folder."""
        if not self.checkpoint_path.exists(): return
        try:
            import shutil
            target = config.ARCHIVED_CHECKPOINTS_DIR / self.checkpoint_path.name
            shutil.move(str(self.checkpoint_path), str(target))
            logger.info(f"[Progress] 📦 Archived checkpoint to: {target.name}")
        except Exception as e:
            logger.error(f"[Progress] Archiving failed: {e}")
