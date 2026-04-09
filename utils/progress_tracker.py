import json
import os
from pathlib import Path
from typing import Dict, List, Set

class ProgressTracker:
    """
    Tracks the processing progress of files using a single JSON file.
    This replaces the need to scan large Excel files for synchronization.
    """

    def __init__(self, state_file: Path):
        self.state_file = state_file
        self.state: Dict[str, List[int]] = {}  # file_key -> list of completed row_indices
        self.load()

    def load(self):
        """Load state from the JSON file."""
        if self.state_file.exists():
            try:
                with open(self.state_file, 'r', encoding='utf-8') as f:
                    self.state = json.load(f)
            except Exception:
                self.state = {}
        else:
            self.state = {}

    def save(self):
        """Save current state to the JSON file."""
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        with open(self.state_file, 'w', encoding='utf-8') as f:
            json.dump(self.state, f, indent=2)

    def mark_row_done(self, file_key: str, row_index: int):
        """Mark a specific row index as completed for a given file."""
        if file_key not in self.state:
            self.state[file_key] = []
        if row_index not in self.state[file_key]:
            self.state[file_key].append(row_index)
            self.save()

    def get_completed_rows(self, file_key: str) -> Set[int]:
        """Return the set of completed row indices for a file."""
        return set(self.state.get(file_key, []))

    def clear_file(self, file_key: str):
        """Remove progress tracking for a file (e.g., after archiving)."""
        if file_key in self.state:
            del self.state[file_key]
            self.save()

    def is_row_done(self, file_key: str, row_index: int) -> bool:
        """Check if a row has already been processed."""
        return row_index in self.get_completed_rows(file_key)
