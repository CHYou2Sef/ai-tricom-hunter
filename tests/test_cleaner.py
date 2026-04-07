"""
tests/test_cleaner.py — Unit tests for excel/cleaner.py

Run with:
    pytest tests/test_cleaner.py -v
"""

import os
import sys
import tempfile

import pytest
import openpyxl

# Make sure the project root is on the import path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from excel.cleaner import (
    CAT_STD, CAT_RS, CAT_SIR, CAT_OTHER, CAT_DISCARD,
    classify_row, clean_and_classify,
)


# ─────────────────────────────────────────────────────────────────────────────
# HELPERS — build lightweight ExcelRow-like objects for testing
# ─────────────────────────────────────────────────────────────────────────────

class MockRow:
    """Minimal stand-in for ExcelRow — only the fields classify_row() uses."""

    def __init__(self, nom=None, adresse=None, siren=None, raw=None):
        self.nom     = nom
        self.adresse = adresse
        self.siren   = siren     # holds SIREN *or* SIRET
        self.raw     = raw or {}
        self.row_index = 1
        self.status    = "DONE"
        self.phone     = None
        self.agent_phone = None


# ─────────────────────────────────────────────────────────────────────────────
# UNIT TESTS — classify_row()
# ─────────────────────────────────────────────────────────────────────────────

class TestClassifyRow:

    def test_std_input_all_three(self):
        """SIREN + RS + Adresse → std_input"""
        row = MockRow(nom="ACME SARL", adresse="12 Rue de la Paix, Paris", siren="123456789")
        assert classify_row(row) == CAT_STD

    def test_rs_input_no_siren(self):
        """RS + Adresse, no SIREN → RS_input"""
        row = MockRow(nom="ACME SARL", adresse="12 Rue de la Paix, Paris", siren=None)
        assert classify_row(row) == CAT_RS

    def test_sir_input_siren_adresse_no_rs(self):
        """SIREN + Adresse, no RS → sir_input"""
        row = MockRow(nom=None, adresse="12 Rue de la Paix, Paris", siren="123456789")
        assert classify_row(row) == CAT_SIR

    def test_other_siren_only(self):
        """Only SIREN, no address → other_input"""
        row = MockRow(nom=None, adresse=None, siren="123456789")
        assert classify_row(row) == CAT_OTHER

    def test_other_adresse_only(self):
        """Only address → other_input"""
        row = MockRow(nom=None, adresse="12 Rue de la Paix", siren=None)
        assert classify_row(row) == CAT_OTHER

    def test_other_rs_only(self):
        """Only RS (no address, no siren) → other_input"""
        row = MockRow(nom="ACME SARL", adresse=None, siren=None)
        assert classify_row(row) == CAT_OTHER

    def test_discard_completely_empty(self):
        """No fields at all → DISCARD"""
        row = MockRow(nom=None, adresse=None, siren=None)
        assert classify_row(row) == CAT_DISCARD

    def test_discard_empty_strings(self):
        """Empty strings should be treated as None → DISCARD"""
        row = MockRow(nom="", adresse="", siren="")
        # nom/adresse/siren are already None because reader strips empties;
        # MockRow passes them as empty strings → classify_row sees falsy
        assert classify_row(row) == CAT_DISCARD

    def test_discard_but_has_tel_saved(self):
        """Row with only a phone column → other_input (not discarded)"""
        row = MockRow(raw={"telephone": "01 23 45 67 89"})
        assert classify_row(row) == CAT_OTHER


# ─────────────────────────────────────────────────────────────────────────────
# INTEGRATION TEST — clean_and_classify() writes correct files
# ─────────────────────────────────────────────────────────────────────────────

class TestCleanAndClassify:

    def _make_row(self, nom=None, adresse=None, siren=None, headers=None):
        row = MockRow(nom=nom, adresse=adresse, siren=siren)
        row.raw = {h: None for h in (headers or [])}
        if nom:
            row.raw["Dénomination"] = nom
        if adresse:
            row.raw["Adresse"] = adresse
        if siren:
            row.raw["SIREN"] = siren
        return row

    def test_files_created_in_correct_dirs(self, tmp_path, monkeypatch):
        """clean_and_classify should write files into the right sub-dirs."""
        import config

        # Redirect config dirs to tmp_path
        monkeypatch.setattr(config, "INPUT_STD_DIR",   str(tmp_path / "std_input"))
        monkeypatch.setattr(config, "INPUT_RS_DIR",    str(tmp_path / "RS_input"))
        monkeypatch.setattr(config, "INPUT_SIR_DIR",   str(tmp_path / "sir_input"))
        monkeypatch.setattr(config, "INPUT_OTHER_DIR", str(tmp_path / "other_input"))

        # Create the dirs (normally done by main.py ensure_directories)
        for d in [config.INPUT_STD_DIR, config.INPUT_RS_DIR,
                  config.INPUT_SIR_DIR, config.INPUT_OTHER_DIR]:
            os.makedirs(d, exist_ok=True)

        headers = ["Dénomination", "Adresse", "SIREN"]
        rows = [
            self._make_row(nom="ACME SARL", adresse="Paris", siren="123456789", headers=headers),
            self._make_row(nom="BETA SAS",  adresse="Lyon",  siren=None,        headers=headers),
            self._make_row(nom=None,        adresse="Lille", siren="987654321",  headers=headers),
        ]

        source = str(tmp_path / "source.xlsx")
        stats = clean_and_classify(rows, source, headers)

        assert stats[CAT_STD]   == 1
        assert stats[CAT_RS]    == 1
        assert stats[CAT_SIR]   == 1
        assert stats[CAT_OTHER] == 0

        assert os.path.exists(str(tmp_path / "std_input"  / "source.xlsx"))
        assert os.path.exists(str(tmp_path / "RS_input"   / "source.xlsx"))
        assert os.path.exists(str(tmp_path / "sir_input"  / "source.xlsx"))

    def test_discard_row_not_written(self, tmp_path, monkeypatch):
        """Rows with no fields should be discarded (no file for DISCARD)."""
        import config

        monkeypatch.setattr(config, "INPUT_STD_DIR",   str(tmp_path / "std_input"))
        monkeypatch.setattr(config, "INPUT_RS_DIR",    str(tmp_path / "RS_input"))
        monkeypatch.setattr(config, "INPUT_SIR_DIR",   str(tmp_path / "sir_input"))
        monkeypatch.setattr(config, "INPUT_OTHER_DIR", str(tmp_path / "other_input"))

        for d in [config.INPUT_STD_DIR, config.INPUT_RS_DIR,
                  config.INPUT_SIR_DIR, config.INPUT_OTHER_DIR]:
            os.makedirs(d, exist_ok=True)

        headers = ["Dénomination", "Adresse", "SIREN"]
        rows = [MockRow(nom=None, adresse=None, siren=None)]

        source = str(tmp_path / "empty.xlsx")
        stats = clean_and_classify(rows, source, headers)

        # Nothing written anywhere
        assert stats[CAT_STD]   == 0
        assert stats[CAT_RS]    == 0
        assert stats[CAT_SIR]   == 0
        assert stats[CAT_OTHER] == 0
