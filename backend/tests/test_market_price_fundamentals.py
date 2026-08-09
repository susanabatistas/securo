from __future__ import annotations

import pandas as pd
import pytest

from app.providers.market_price import (
    _average_roe_pct,
    _cagr_pct,
    _find_row,
    _net_debt_to_ebitda,
    _row_by_year,
)


def test_net_debt_to_ebitda_computes_ratio():
    info = {"totalDebt": 300.0, "totalCash": 100.0, "ebitda": 100.0}
    assert _net_debt_to_ebitda(info) == pytest.approx(2.0)


def test_net_debt_to_ebitda_none_when_ebitda_missing_or_non_positive():
    assert _net_debt_to_ebitda({"totalDebt": 300.0, "totalCash": 100.0, "ebitda": None}) is None
    assert _net_debt_to_ebitda({"totalDebt": 300.0, "totalCash": 100.0, "ebitda": 0}) is None
    assert _net_debt_to_ebitda({"totalDebt": 300.0, "totalCash": 100.0, "ebitda": -50.0}) is None


def test_net_debt_to_ebitda_none_when_debt_or_cash_missing():
    assert _net_debt_to_ebitda({"totalCash": 100.0, "ebitda": 100.0}) is None


def test_average_roe_pct_averages_years_with_both_figures():
    net_income = {2023: 100.0, 2024: 150.0, 2025: 200.0}
    equity = {2023: 1000.0, 2024: 1000.0, 2025: 1000.0}
    # 10%, 15%, 20% -> average 15%
    assert _average_roe_pct(net_income, equity) == pytest.approx(15.0)


def test_average_roe_pct_skips_years_with_non_positive_equity():
    net_income = {2023: 100.0, 2024: 150.0}
    equity = {2023: 1000.0, 2024: -50.0}
    assert _average_roe_pct(net_income, equity) == pytest.approx(10.0)


def test_average_roe_pct_none_when_no_overlapping_years():
    assert _average_roe_pct({2023: 100.0}, {2024: 1000.0}) is None


def test_cagr_pct_compounds_over_span():
    # 100 -> 121 over 2 years = 10% CAGR
    assert _cagr_pct({2023: 100.0, 2024: 110.0, 2025: 121.0}) == pytest.approx(10.0, rel=1e-6)


def test_cagr_pct_none_with_fewer_than_two_years():
    assert _cagr_pct({2023: 100.0}) is None
    assert _cagr_pct({}) is None


def test_cagr_pct_none_with_non_positive_base():
    assert _cagr_pct({2023: -100.0, 2024: 50.0}) is None


def test_row_by_year_extracts_from_pandas_series_and_caps_to_n_years():
    row = pd.Series(
        {
            pd.Timestamp("2025-12-31"): 500.0,
            pd.Timestamp("2024-12-31"): 400.0,
            pd.Timestamp("2023-12-31"): 300.0,
            pd.Timestamp("2022-12-31"): 200.0,
        }
    )
    result = _row_by_year(row, years=3)
    assert result == {2025: 500.0, 2024: 400.0, 2023: 300.0}


def test_row_by_year_skips_nan():
    row = pd.Series({pd.Timestamp("2025-12-31"): 500.0, pd.Timestamp("2024-12-31"): float("nan")})
    result = _row_by_year(row, years=5)
    assert result == {2025: 500.0}


def test_row_by_year_none_row_returns_empty():
    assert _row_by_year(None, years=5) == {}


def test_find_row_matches_normalized_labels_case_and_spacing_insensitive():
    df = pd.DataFrame(
        {pd.Timestamp("2025-12-31"): [1000.0, 200.0]},
        index=["Total Revenue", "Net Income"],
    )
    revenue = _find_row(df, ("totalrevenue",))
    assert revenue is not None
    assert revenue[pd.Timestamp("2025-12-31")] == 1000.0


def test_find_row_returns_none_when_no_label_matches():
    df = pd.DataFrame({pd.Timestamp("2025-12-31"): [1000.0]}, index=["Something Else"])
    assert _find_row(df, ("totalrevenue",)) is None


def test_find_row_returns_none_for_none_or_empty_df():
    assert _find_row(None, ("totalrevenue",)) is None
    assert _find_row(pd.DataFrame(), ("totalrevenue",)) is None
