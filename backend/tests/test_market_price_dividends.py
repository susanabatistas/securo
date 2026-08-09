from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from app.providers.market_price import CompositeMarketPriceProvider, YFinanceProvider


def _fake_series():
    return pd.Series(
        {
            pd.Timestamp("2026-01-10", tz="America/Sao_Paulo"): 0.5,
            pd.Timestamp("2026-02-10", tz="America/Sao_Paulo"): 0.6,
            pd.Timestamp("2026-03-10", tz="America/Sao_Paulo"): 0.7,
        }
    )


def test_dividend_history_sync_parses_series(monkeypatch):
    class FakeTicker:
        dividends = _fake_series()

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", lambda symbol: FakeTicker())

    events = YFinanceProvider._dividend_history_sync("PETR4.SA", None)
    assert len(events) == 3
    assert events[0].date == date(2026, 1, 10)
    assert events[0].amount == 0.5


def test_dividend_history_sync_filters_since(monkeypatch):
    class FakeTicker:
        dividends = _fake_series()

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", lambda symbol: FakeTicker())

    events = YFinanceProvider._dividend_history_sync("PETR4.SA", date(2026, 2, 1))
    assert len(events) == 2
    assert all(e.date >= date(2026, 2, 1) for e in events)


def test_dividend_history_sync_empty_on_upstream_failure(monkeypatch):
    class FakeTicker:
        @property
        def dividends(self):
            raise RuntimeError("boom")

    import yfinance as yf
    monkeypatch.setattr(yf, "Ticker", lambda symbol: FakeTicker())

    assert YFinanceProvider._dividend_history_sync("PETR4.SA", None) == []


@pytest.mark.asyncio
async def test_composite_provider_skips_tesouro_symbols():
    provider = CompositeMarketPriceProvider()
    events = await provider.get_dividend_history("TD:ABCD1234:2029-03-01")
    assert events == []
