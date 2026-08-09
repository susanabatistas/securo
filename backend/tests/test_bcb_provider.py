from __future__ import annotations

from datetime import date
from decimal import Decimal

from app.providers.bcb import BCBQuote, _parse_decimal, _parse_series, compound_cdi


def test_parse_decimal_accepts_comma_and_dot():
    assert _parse_decimal("0,87") == Decimal("0.87")
    assert _parse_decimal("0.87") == Decimal("0.87")


def test_parse_series_from_raw_bcb_json():
    raw = [
        {"data": "01/06/2026", "valor": "0.87"},
        {"data": "01/07/2026", "valor": "0.90"},
    ]
    quotes = _parse_series(raw)
    assert quotes == [
        BCBQuote(value=Decimal("0.87"), date=date(2026, 6, 1)),
        BCBQuote(value=Decimal("0.90"), date=date(2026, 7, 1)),
    ]


def test_parse_series_skips_malformed_rows():
    raw = [{"data": "01/06/2026", "valor": "0.87"}, {"data": "not-a-date", "valor": "0.90"}, {}]
    quotes = _parse_series(raw)
    assert len(quotes) == 1


def test_compound_cdi_compounds_not_sums():
    # Two months of 1% each compound to slightly more than 2%.
    quotes = [
        BCBQuote(value=Decimal("1.0"), date=date(2026, 6, 1)),
        BCBQuote(value=Decimal("1.0"), date=date(2026, 7, 1)),
    ]
    result = compound_cdi(quotes)
    assert result is not None
    # 1.01 * 1.01 = 1.0201 -> 2.01%, not a naive 2.0% sum.
    assert result == Decimal("2.01")
    assert result > Decimal("2.0")


def test_compound_cdi_empty_returns_none():
    assert compound_cdi([]) is None
