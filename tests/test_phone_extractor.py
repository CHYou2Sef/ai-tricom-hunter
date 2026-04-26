"""
╔══════════════════════════════════════════════════════════════════════════╗
║  tests/test_phone_extractor.py                                           ║
║                                                                          ║
║  Unit tests for anti-hallucination validators (Bugs #1, #6).            ║
║  Covers: normalize_phone(), is_valid_french_phone(), blocklist,          ║
║  structural checks (all-same-digit, sequential).                         ║
║                                                                          ║
║  Run: pytest tests/test_phone_extractor.py -v                           ║
╚══════════════════════════════════════════════════════════════════════════╝
"""
import pytest
from unittest.mock import patch, MagicMock

# We mock the logger to avoid needing the full logging infrastructure
with patch("core.logger.get_logger", return_value=MagicMock()):
    from domain.search.phone_extractor import (
        normalize_phone,
        is_valid_french_phone,
        format_french,
        get_best_phone,
    )


# ── Fake / hallucinated phones that MUST be blocked ──────────────────────────

FAKE_PHONES = [
    ("01 23 45 67 89", "classic sequential demo — in blocklist"),
    ("0123456789",     "same without spaces"),
    ("00 00 00 00 00", "all-zero"),
    ("03 33 33 33 33", "all-3 variant — in blocklist"),
    ("06 00 00 00 00", "generic mobile placeholder"),
    ("07 00 00 00 00", "generic mobile placeholder 07"),
    ("01 00 00 00 00", "landline all-zero"),
]


@pytest.mark.parametrize("phone,label", FAKE_PHONES)
def test_fake_phones_are_blocked(phone, label):
    """normalize_phone() must return None for any blocked/fake number."""
    result = normalize_phone(phone)
    assert result is None, (
        f"SECURITY LEAK — fake phone passed validation: {phone!r} ({label}) → {result!r}"
    )


# ── Real phones that MUST pass through correctly ─────────────────────────────

REAL_PHONES = [
    ("06 12 34 56 78", "06 12 34 56 78", "standard mobile"),
    ("07 89 01 23 45", "07 89 01 23 45", "mobile 07"),
    ("01 45 67 89 01", "01 45 67 89 01", "Paris landline"),
    ("04 91 12 34 56", "04 91 12 34 56", "Marseille landline"),
    ("+33 6 12 34 56 78", "06 12 34 56 78", "+33 international → local"),
    ("+33145678901",      "01 45 67 89 01", "+33 no spaces compact"),
    ("06.12.34.56.78",    "06 12 34 56 78", "dot-separated"),
    ("06-12-34-56-78",    "06 12 34 56 78", "dash-separated"),
]


@pytest.mark.parametrize("raw,expected,label", REAL_PHONES)
def test_real_phones_normalized_correctly(raw, expected, label):
    """normalize_phone() must return the correctly formatted string."""
    result = normalize_phone(raw)
    assert result == expected, (
        f"REAL phone incorrectly blocked: {raw!r} ({label}) → {result!r}, expected {expected!r}"
    )


# ── Structural validator ──────────────────────────────────────────────────────

class TestIsValidFrenchPhone:

    def test_sequential_ascending_rejected(self):
        """0123456789 is the canonical sequential hallucination."""
        assert is_valid_french_phone("0123456789") is False

    def test_all_same_digit_rejected(self):
        """Pure all-same-digit numbers like 0000000000 are placeholders."""
        assert is_valid_french_phone("0000000000") is False

    def test_blocklist_hit_rejected(self):
        """0123456789 is also in the hard blocklist."""
        assert is_valid_french_phone("0123456789") is False

    def test_real_mobile_passes(self):
        assert is_valid_french_phone("0612345678") is True

    def test_real_paris_landline_passes(self):
        assert is_valid_french_phone("0145678901") is True

    def test_real_marseille_passes(self):
        assert is_valid_french_phone("0491123456") is True

    def test_7_prefix_passes(self):
        """07 numbers are valid French mobiles."""
        assert is_valid_french_phone("0789012345") is True


# ── format_french() ───────────────────────────────────────────────────────────

class TestFormatFrench:

    def test_formats_10_digits(self):
        assert format_french("0612345678") == "06 12 34 56 78"

    def test_wrong_length_returns_raw(self):
        """format_french is a pure formatter — doesn't validate."""
        assert format_french("123") == "123"


# ── get_best_phone() ─────────────────────────────────────────────────────────

class TestGetBestPhone:

    def test_prefers_mobile(self):
        phones = ["01 45 67 89 01", "06 12 34 56 78"]
        assert get_best_phone(phones) == "06 12 34 56 78"

    def test_falls_back_to_first(self):
        phones = ["01 45 67 89 01", "04 91 12 34 56"]
        assert get_best_phone(phones) == "01 45 67 89 01"

    def test_empty_returns_none(self):
        assert get_best_phone([]) is None

    def test_single_mobile(self):
        assert get_best_phone(["07 89 01 23 45"]) == "07 89 01 23 45"
