import pytest
from unittest.mock import MagicMock
from agents.phone_hunter import build_search_query
# _fill_missing_siren was deprecated in favor of LLM-based enrichment
from domain.excel.reader import ExcelRow

def test_build_search_query_with_name_and_address():
    """Test SQO generation when full name and address are present."""
    mock_row = MagicMock(spec=ExcelRow)
    mock_row.nom = "ACME Corp"
    mock_row.siren = "123456789"
    mock_row.adresse = "123 Main St, Paris"
    # get_search_name() is a method — MagicMock stubs it; set explicit return
    mock_row.get_search_name.return_value = "ACME Corp"

    query = build_search_query(mock_row)

    assert "ACME Corp" in query
    assert "123 Main St, Paris" in query
    # build_b2b_query appends a simple intent hint (no dorking — avoids anti-bot)
    assert "téléphone contact" in query

def test_build_search_query_siren_only():
    """Test SQO generation when only SIREN is present."""
    mock_row = MagicMock(spec=ExcelRow)
    mock_row.nom = None
    mock_row.siren = "987654321"
    mock_row.adresse = None
    # When nom is None, get_search_name() falls back to siren
    mock_row.get_search_name.return_value = "987654321"

    query = build_search_query(mock_row)

    assert "987654321" in query
    assert "ACME Corp" not in query

# def test_fill_missing_siren():
#     """Test the regex behavior for SIREN insertion from HTML."""
#     mock_row = MagicMock(spec=ExcelRow)
#     mock_row.nom = "Test"
#     mock_row.siren = None 
#     
#     # 9 digit pattern
#     html_content = "<html><body>Welcome to Test Corp. SIREN: 111222333 </body></html>"
#     _fill_missing_siren(mock_row, html_content)
#     
#     assert mock_row.siren == "111222333"

# def test_fill_missing_siren_false_positive():
#     """Ensure it does not match normal numbers or short strings."""
#     mock_row = MagicMock(spec=ExcelRow)
#     mock_row.nom = "Test"
#     mock_row.siren = None 
#     
#     # Not 9 digits consecutively (spaces, dots, or < 9)
#     html_content = "Call us at 111 222 33 and check id 12345."
#     _fill_missing_siren(mock_row, html_content)
#     
#     # Should remain empty
#     assert mock_row.siren is None
