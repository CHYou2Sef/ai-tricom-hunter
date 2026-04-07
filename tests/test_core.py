import pytest
from unittest.mock import MagicMock
from agent import build_search_query, _fill_missing_siren
from excel.reader import ExcelRow

def test_build_search_query_with_name_and_address():
    """Test SQO generation when full name and address are present."""
    mock_row = MagicMock(spec=ExcelRow)
    mock_row.nom = "ACME Corp"
    mock_row.siren = "123456789"
    mock_row.adresse = "123 Main St, Paris"
    
    query = build_search_query(mock_row)
    
    assert "ACME Corp" in query
    assert "123 Main St, Paris" in query
    # Should contain Dorking trusted domains
    assert "site:pappers.fr" in query or "site:societe.com" in query

def test_build_search_query_siren_only():
    """Test SQO generation when only SIREN is present."""
    mock_row = MagicMock(spec=ExcelRow)
    mock_row.nom = None
    mock_row.siren = "987654321"
    mock_row.adresse = None
    
    query = build_search_query(mock_row)
    
    assert "987654321" in query
    assert "ACME Corp" not in query

def test_fill_missing_siren():
    """Test the regex behavior for SIREN insertion from HTML."""
    mock_row = MagicMock(spec=ExcelRow)
    mock_row.nom = "Test"
    mock_row.siren = None 
    
    # 9 digit pattern
    html_content = "<html><body>Welcome to Test Corp. SIREN: 111222333 </body></html>"
    _fill_missing_siren(mock_row, html_content)
    
    assert mock_row.siren == "111222333"

def test_fill_missing_siren_false_positive():
    """Ensure it does not match normal numbers or short strings."""
    mock_row = MagicMock(spec=ExcelRow)
    mock_row.nom = "Test"
    mock_row.siren = None 
    
    # Not 9 digits consecutively (spaces, dots, or < 9)
    html_content = "Call us at 111 222 33 and check id 12345."
    _fill_missing_siren(mock_row, html_content)
    
    # Should remain empty
    assert mock_row.siren is None
