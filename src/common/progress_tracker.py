"""
common/progress_tracker.py - Per-File Crash Recovery + GLOBAL_PHONE_SET

ROLE:
  Saves row-by-row processing results to JSON for crash recovery.
  GLOBAL_PHONE_SET prevents duplicate phone collection across runs
  (container crash, PC reboot, IP ban restart scenarios).
"""

import json
import os
import re
from pathlib import Path
from typing import Dict, Any, Optional, Set

from core import config
from core.logger import get_logger

logger = get_logger(__name__)


class FileProgressTracker:
    """
    Persistent state tracker for crash recovery + global phone dedup.
    """
    GLOBAL_PHONE_SET_FILE = "GLOBAL_PHONE_SET.json"

    def __init__(self, original_filepath: str):
        self.original_path = Path(original_filepath)
        self.checkpoint_path = config.CHECKPOINTS_DIR / f"{self.original_path.name}.json"
        self.data: Dict[str, Any] = {}
        self._global_phones: Set[str] = set()
        self._global_set_path = config.CHECKPOINTS_DIR / self.GLOBAL_PHONE_SET_FILE
        self.load()
        self._sync_global_from_checkpoints()

    def load(self):
        """Load checkpoint + global PHONE_SET."""
        target = self.checkpoint_path

        if not target.exists():
            archived = config.ARCHIVED_CHECKPOINTS_DIR / target.name
            if archived.exists():
                target = archived
                logger.info(f"[Progress] Using ARCHIVED checkpoint: {target.name}")
            else:
                stem = self.original_path.stem
                matches = list(config.CHECKPOINTS_DIR.glob(f"*{stem}*.json"))
                if matches:
                    target = matches[0]
                    logger.info(f"[Progress] Fuzzy match: {target.name}")

        # Load global PHONE_SET first
        self._load_global_phone_set()

        if target.exists():
            try:
                with open(target, 'r', encoding='utf-8') as f:
                    self.data = json.load(f)
                logger.info(f"[Progress] Loaded {len(self.data)} rows")
            except Exception as e:
                logger.warning(f"[Progress] Load failed: {e}")
                self.data = {}
        else:
            self.data = {}

    def _load_global_phone_set(self):
        """Load the global PHONE_SET from shared checkpoint file."""
        if self._global_set_path.exists():
            try:
                with open(self._global_set_path, 'r', encoding='utf-8') as f:
                    self._global_phones = set(json.load(f))
                logger.info(f"[Progress] Global PHONE_SET: {len(self._global_phones)} phones")
            except Exception as e:
                logger.warning(f"[Progress] Failed to load global PHONE_SET: {e}")

    def _sync_global_from_checkpoints(self):
        """Sync all phones from current checkpoint into global set."""
        for idx, entry in self.data.items():
            if idx.startswith("__"):
                continue
            for phone_field in ("phone", "agent_phone"):
                phone = entry.get(phone_field)
                if phone:
                    self._global_phones.add(self._normalize_phone(phone))

    @staticmethod
    def _normalize_phone(phone: str) -> str:
        """
        Normalize phone to last 9 digits for French mobile dedup.
        Handles: +33, spaces, dashes, country codes.
        """
        if not phone:
            return ""
        digits = re.sub(r"[^\d]", "", str(phone))
        # Strip leading 33/0033
        if digits.startswith("33") and len(digits) == 11:
            digits = "0" + digits[2:]
        elif digits.startswith("0033") and len(digits) == 12:
            digits = "0" + digits[4:]
        return digits[-9:] if len(digits) >= 9 else digits

    def is_phone_duplicated(self, phone: str) -> bool:
        """
        Check if this phone was already collected in ANY previous run.
        Prevents duplicates from container crash, PC reboot, IP ban restart.
        """
        if not phone:
            return False
        return self._normalize_phone(phone) in self._global_phones

    def register_phone(self, phone: str) -> None:
        """Add a phone to the global dedup set."""
        if phone:
            self._global_phones.add(self._normalize_phone(phone))

    def save(self):
        """Save checkpoint + global PHONE_SET."""
        try:
            with open(self.checkpoint_path, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Progress] Failed to save checkpoint: {e}")
        try:
            with open(self._global_set_path, 'w', encoding='utf-8') as f:
                json.dump(list(self._global_phones), f, ensure_ascii=False)
        except Exception as e:
            logger.error(f"[Progress] Failed to save global PHONE_SET: {e}")

    def mark_row_done(self, row_index: int, phone: Optional[str], agent_phone: Optional[str], status: str, extra: dict = None):
        """Record row result with auto-registration to global dedup."""
        entry = {"phone": phone, "agent_phone": agent_phone, "status": status}
        if extra:
            entry.update(extra)
        self.data[str(row_index)] = entry
        if phone:
            self.register_phone(phone)
        if agent_phone:
            self.register_phone(agent_phone)
        self.save()

    def get_row_data(self, row_index: int) -> Optional[dict]:
        return self.data.get(str(row_index))

    def is_row_done(self, row_index: int) -> bool:
        return str(row_index) in self.data

    def delete(self):
        if self.checkpoint_path.exists():
            try:
                os.remove(self.checkpoint_path)
            except Exception as e:
                logger.error(f"[Progress] Cleanup failed: {e}")

    def archive(self):
        """Archive checkpoint, preserve global PHONE_SET."""
        if not self.checkpoint_path.exists():
            return
        try:
            import shutil
            target = config.ARCHIVED_CHECKPOINTS_DIR / self.checkpoint_path.name
            shutil.move(str(self.checkpoint_path), str(target))
            logger.info(f"[Progress] Archived: {target.name}")
        except Exception as e:
            logger.error(f"[Progress] Archive failed: {e}")

    def get_global_phone_count(self) -> int:
        return len(self._global_phones)
