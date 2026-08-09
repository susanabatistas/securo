import uuid
from datetime import date

from app.schemas.asset import AssetRead
from app.services.ir_estimator_service import (
    STOCK_ETF_CRYPTO_NOTE,
    estimate_asset,
    estimate_portfolio,
    regressive_rate_pct,
)

TODAY = date(2026, 8, 9)


def _asset(**overrides) -> AssetRead:
    base = dict(
        id=uuid.uuid4(),
        user_id=uuid.uuid4(),
        name="Test Asset",
        type="stock",
        currency="BRL",
        valuation_method="market_price",
        is_archived=False,
        position=0,
        ticker="PETR4.SA",
        purchase_date=date(2025, 1, 1),
        gain_loss=1000.0,
        gain_loss_primary=None,
        tax_category="acoes_etfs_cripto",
    )
    base.update(overrides)
    return AssetRead(**base)


def test_regressive_rate_pct_thresholds():
    assert regressive_rate_pct(1) == 22.5
    assert regressive_rate_pct(180) == 22.5
    assert regressive_rate_pct(181) == 20.0
    assert regressive_rate_pct(360) == 20.0
    assert regressive_rate_pct(361) == 17.5
    assert regressive_rate_pct(720) == 17.5
    assert regressive_rate_pct(721) == 15.0
    assert regressive_rate_pct(3650) == 15.0


def test_estimate_asset_none_when_no_tax_category():
    asset = _asset(tax_category=None)
    assert estimate_asset(asset, today=TODAY) is None


def test_estimate_asset_none_when_no_gain():
    assert estimate_asset(_asset(gain_loss=0.0), today=TODAY) is None
    assert estimate_asset(_asset(gain_loss=-500.0), today=TODAY) is None
    assert estimate_asset(_asset(gain_loss=None), today=TODAY) is None


def test_estimate_asset_acoes_etfs_cripto_15pct_with_note():
    asset = _asset(tax_category="acoes_etfs_cripto", gain_loss=1000.0)
    result = estimate_asset(asset, today=TODAY)
    assert result is not None
    assert result.rate_pct == 15.0
    assert result.estimated_tax == 150.0
    assert result.note == STOCK_ETF_CRYPTO_NOTE


def test_estimate_asset_fii_20pct_flat_no_note():
    asset = _asset(type="fund", tax_category="fii", gain_loss=1000.0)
    result = estimate_asset(asset, today=TODAY)
    assert result is not None
    assert result.rate_pct == 20.0
    assert result.estimated_tax == 200.0
    assert result.note is None


def test_estimate_asset_renda_fixa_uses_regressive_table_from_purchase_date():
    # 2023-01-01 -> 2026-08-09 is well over 720 days -> 15%.
    purchase_date = date(2023, 1, 1)
    asset = _asset(
        type="investment", tax_category="renda_fixa", ticker=None,
        purchase_date=purchase_date, gain_loss=1000.0,
    )
    result = estimate_asset(asset, today=TODAY)
    assert result is not None
    assert result.days_held == (TODAY - purchase_date).days
    assert result.rate_pct == 15.0
    assert result.estimated_tax == 150.0


def test_estimate_asset_renda_fixa_short_holding_higher_rate():
    asset = _asset(
        type="investment", tax_category="renda_fixa", ticker=None,
        purchase_date=date(2026, 7, 1), gain_loss=1000.0,  # ~39 days
    )
    result = estimate_asset(asset, today=TODAY)
    assert result is not None
    assert result.rate_pct == 22.5


def test_estimate_asset_renda_fixa_none_without_purchase_date():
    asset = _asset(
        type="investment", tax_category="renda_fixa", ticker=None,
        purchase_date=None, gain_loss=1000.0,
    )
    assert estimate_asset(asset, today=TODAY) is None


def test_estimate_asset_prefers_gain_loss_primary_when_present():
    asset = _asset(currency="USD", gain_loss=100.0, gain_loss_primary=550.0)
    result = estimate_asset(asset, today=TODAY)
    assert result is not None
    assert result.gain == 550.0
    assert result.estimated_tax == 550.0 * 0.15


def test_estimate_portfolio_sums_across_assets_and_skips_non_applicable():
    assets = [
        _asset(tax_category="acoes_etfs_cripto", gain_loss=1000.0),  # 150
        _asset(type="fund", tax_category="fii", gain_loss=500.0),  # 100
        _asset(type="real_estate", tax_category=None, gain_loss=99999.0),  # excluded
        _asset(gain_loss=-10.0),  # no gain, excluded
    ]
    response = estimate_portfolio(assets, today=TODAY)
    assert len(response.assets) == 2
    assert response.total_estimated_tax == 250.0
    assert "estimativa" in response.disclaimer.lower()
