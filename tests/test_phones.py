import sys
from pathlib import Path
from unittest.mock import MagicMock
sys.path.append(str(Path(__file__).parent))

from src.domain.search.phone_extractor import normalize_phone, get_phone_metadata
from src.agents.phone_hunter import _calculate_row_confidence
from src.domain.excel.reader import ExcelRow

def test_phones():
    test_cases = [
        "01 40 20 50 50", # valid fixed line (louvre)
        "06 12 34 56 78", # valid mobile
        "01 23 45 67 89", # sequential ascending
        "06 66 66 66 66", # same digits
        "99 99 99 99 99", # invalid FR number
        "0000000000"      # fake number
    ]
    
    print("=== Extraction Tests ===")
    for p in test_cases:
        norm = normalize_phone(p)
        meta = get_phone_metadata(norm)
        print(f"Input: {p:15s} | Normalized: {str(norm):15s} | Type: {meta.get('type')}")

    print("\n=== Confidence Scoring ===")
    # ExcelRow ctor takes (raw, row_index, mapping) — use a MagicMock to
    # avoid coupling this unit test to internal construction details.
    row = MagicMock(spec=ExcelRow)
    row.row_index = 1
    row.nom = "Test Company"
    row.adresse = "Paris"
    row.siren = "123456789"
    row.phone = ""
    row.agent_phone = None
    row.enriched_fields = {}
    row.raw_ai_responses = []
    row.search_queries_used = []
    row.status = ""
    
    # Simulate a good match
    row.phone = "01 40 20 50 50"
    row.enriched_fields["phone_list"] = [
        {"num": "01 40 20 50 50", "score": 90, "source": "google_kp"},
        {"num": "01 40 20 50 50", "score": 85, "source": "web_scrap"}
    ]
    score1 = _calculate_row_confidence(row)
    print(f"Good Match Score: {score1}/100 (Expected: High)")
    
    # Simulate SIREN mismatch
    row.enriched_fields["validation_error"] = "SIREN_MISMATCH"
    score2 = _calculate_row_confidence(row)
    print(f"SIREN Mismatch Score: {score2}/100 (Expected: Lower by 25)")
    
if __name__ == "__main__":
    test_phones()
