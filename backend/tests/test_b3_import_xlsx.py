"""Tests for B3 import with XLSX support."""
import pytest
from app.services.b3_import_service import parse_b3_csv, _is_xlsx


def test_is_xlsx_detects_xlsx_files():
    """Test that _is_xlsx correctly identifies XLSX files by magic bytes."""
    # XLSX files start with PK (ZIP signature)
    xlsx_magic = b'PK\x03\x04'
    assert _is_xlsx(xlsx_magic + b'some other data')
    assert _is_xlsx(b'PK\x00\x00\x00')
    
    # CSV files don't start with PK
    csv_content = b'Movimentacao;Data;Produto;Quantidade'
    assert not _is_xlsx(csv_content)
    
    # Empty
    assert not _is_xlsx(b'')


def test_parse_b3_csv_with_xlsx_conversion():
    """Test that parse_b3_csv can accept XLSX files (with openpyxl installed).
    
    This test creates a minimal XLSX file structure and verifies that it's
    converted to CSV and parsed correctly.
    """
    try:
        import openpyxl
        from openpyxl import Workbook
        import io
    except ImportError:
        pytest.skip("openpyxl not available")
    
    # Create a minimal XLSX workbook in memory
    wb = Workbook()
    ws = wb.active
    
    # Header row
    ws.append([
        'Entrada/Saída', 'Data', 'Movimentação', 'Produto', 'Instituição',
        'Quantidade', 'Preço unitário', 'Valor da Operação'
    ])
    
    # Sample buy row
    ws.append([
        'C', '12/03/2024', 'Compra', 'PETR4 - PETROBRAS PN', 'B3',
        '100', '30.00', '3000.00'
    ])
    
    # Save to bytes
    excel_bytes = io.BytesIO()
    wb.save(excel_bytes)
    excel_bytes.seek(0)
    content = excel_bytes.read()
    
    # Verify it's detected as XLSX
    assert _is_xlsx(content)
    
    # Parse it - should convert XLSX to CSV and parse successfully
    result = parse_b3_csv(content)
    
    assert len(result.rows) == 1
    # _extract_ticker always appends ".SA" (B3's export is exclusively
    # Brazilian securities, and the rest of Securo stores BR tickers with
    # that suffix) — see the regression this fixed in b3_import_service.
    assert result.rows[0].ticker == 'PETR4.SA'
    assert result.rows[0].kind == 'buy'
    assert result.rows[0].quantity == 100
    
    
def test_parse_b3_csv_handles_xlsx_errors():
    """Test that invalid XLSX files raise clear errors."""
    # Invalid XLSX (just ZIP header without valid Excel structure)
    invalid_xlsx = b'PK\x03\x04\x00\x00\x00\x00\x00\x00garbage'
    
    with pytest.raises(ValueError) as exc_info:
        parse_b3_csv(invalid_xlsx)
    
    assert 'XLSX' in str(exc_info.value) or 'Excel' in str(exc_info.value).title()
