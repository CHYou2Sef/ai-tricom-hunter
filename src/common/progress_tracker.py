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
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, Set

from core import config
from core.logger import get_logger

# How often to persist GLOBAL_PHONE_SET (rows).  Lower = safer but more I/O.
_PHONE_SET_SAVE_INTERVAL: int = int(os.environ.get("PHONE_SET_SAVE_INTERVAL", "10"))

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
        # Counter: how many rows have been processed since the last phone-set flush
        self._phone_set_dirty_count: int = 0
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
                with open(target, "r", encoding="utf-8") as f:
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
                with open(self._global_set_path, "r", encoding="utf-8") as f:
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

    @staticmethod
    def _atomic_write(path: Path, payload: str) -> None:
        """
        Write *payload* to *path* atomically using a temp file + os.replace().

        On POSIX, os.replace() is guaranteed atomic at the filesystem level:
        readers will always see either the old or the new file, never a
        partially-written one.  This prevents JSON corruption on SIGKILL or
        power loss.
        """
        dir_ = path.parent
        dir_.mkdir(parents=True, exist_ok=True)
        fd, tmp_path = tempfile.mkstemp(dir=dir_, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
            os.replace(tmp_path, path)  # atomic on POSIX
        except Exception:
            # Clean up orphan temp file on failure
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
            raise

    def save(self):
        """Atomically persist the per-file checkpoint JSON."""
        try:
            payload = json.dumps(self.data, indent=2, ensure_ascii=False)
            self._atomic_write(self.checkpoint_path, payload)
        except Exception as e:
            logger.error(f"[Progress] Failed to save checkpoint: {e}")

    def flush_global_phone_set(self) -> None:
        """
        Force-persist GLOBAL_PHONE_SET to disk immediately.

        Call this at the end of a run (or on graceful shutdown) to guarantee
        the latest phone set is flushed even if the last interval hasn't
        been reached yet.
        """
        try:
            payload = json.dumps(list(self._global_phones), ensure_ascii=False)
            self._atomic_write(self._global_set_path, payload)
            self._phone_set_dirty_count = 0
            logger.debug(f"[Progress] GLOBAL_PHONE_SET flushed ({len(self._global_phones)} phones)")
        except Exception as e:
            logger.error(f"[Progress] Failed to flush global PHONE_SET: {e}")

    def _save_global_phone_set_if_due(self) -> None:
        """
        Throttled GLOBAL_PHONE_SET persistence.

        Writes only when *_phone_set_dirty_count* reaches the configured
        interval, drastically reducing per-row disk I/O on large runs while
        still bounding the exposure window to at most N rows of phone data.
        """
        self._phone_set_dirty_count += 1
        if self._phone_set_dirty_count >= _PHONE_SET_SAVE_INTERVAL:
            self.flush_global_phone_set()

    def mark_row_done(
        self,
        row_index: int,
        phone: Optional[str],
        agent_phone: Optional[str],
        status: str,
        extra: dict = {},
    ) -> None:
        """
        Atomically record a row result and schedule phone-set persistence.

        - The per-file checkpoint is always written atomically on every call
          (cheap: one renamed temp-file per row).
        - GLOBAL_PHONE_SET is flushed only every PHONE_SET_SAVE_INTERVAL rows
          to amortise I/O cost over long runs.  Call flush_global_phone_set()
          explicitly on graceful shutdown.
        """
        entry: dict = {"phone": phone, "agent_phone": agent_phone, "status": status}
        if extra:
            entry.update(extra)
        self.data[str(row_index)] = entry
        phone_added = False
        if phone:
            self.register_phone(phone)
            phone_added = True
        if agent_phone:
            self.register_phone(agent_phone)
            phone_added = True
        # Always save the per-row checkpoint atomically
        self.save()
        # Throttled phone-set flush (only writes every N rows with new phones)
        if phone_added:
            self._save_global_phone_set_if_due()

    def get_row_data(self, row_index: int) -> Optional[dict]:
        return self.data.get(str(row_index))

    def is_row_done(self, row_index: int) -> bool:
        return str(row_index) in self.data

    def get_resume_index(self) -> Optional[int]:
        """
        Return the highest row index already present in the checkpoint.

        Used on restart to log exactly which row the agent resumes from.
        Returns None if the checkpoint is empty (fresh run).
        """
        indices = []
        for key in self.data:
            if key.startswith("__"):
                continue
            try:
                indices.append(int(key))
            except ValueError:
                continue
        return max(indices) if indices else None

    def get_terminal_row_indices(self) -> Set[int]:
        """
        Return the set of row indices that are in a 100% terminal state.

        Terminal = DONE | NO TEL | LOW_CONF | SKIP | DUPLICATE.
        These rows are NEVER re-processed on restart regardless of any config
        flag.  ERROR and PENDING are intentionally excluded so they get a
        second chance on the next run.

        DUPLICATE: phone was found but already registered in GLOBAL_PHONE_SET
        from another file or session. Cannot be placed in output; auditable via
        phone_list in the checkpoint JSON.
        """
        TERMINAL = {"DONE", "NO TEL", "NO_TEL", "LOW_CONF", "SKIP", "DUPLICATE"}
        result: Set[int] = set()
        for key, entry in self.data.items():
            if key.startswith("__"):
                continue
            if isinstance(entry, dict) and entry.get("status") in TERMINAL:
                try:
                    result.add(int(key))
                except ValueError:
                    continue
        return result

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
