from app.services.asset_classification import resolve_asset_type


def test_resolve_asset_type_static_override_beats_ambiguous_quote_type():
    # This is exactly the bug buy_into_holding had: Yahoo reports FIIs as
    # EQUITY, indistinguishable from a stock, without the static override.
    assert resolve_asset_type("HGLG11.SA", "EQUITY") == "fund"
    assert resolve_asset_type("hglg11.sa", "EQUITY") == "fund"
    assert resolve_asset_type("KNRI11", "EQUITY") == "fund"


def test_resolve_asset_type_static_override_for_etfs():
    assert resolve_asset_type("BOVA11.SA", "EQUITY") == "etf"
    assert resolve_asset_type("IVVB11", None) == "etf"


def test_resolve_asset_type_falls_back_to_quote_type():
    assert resolve_asset_type("AAPL", "EQUITY") == "stock"
    assert resolve_asset_type("QQQ", "ETF") == "etf"
    assert resolve_asset_type("BTC-USD", "CRYPTOCURRENCY") == "crypto"


def test_resolve_asset_type_unrecognized_falls_back_to_investment():
    assert resolve_asset_type("XPTO11.SA", None) == "investment"
    assert resolve_asset_type("XPTO11.SA", "BOND") == "investment"
