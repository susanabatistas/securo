"""Deterministic IR (income tax) estimator for BR investors — no AI.

General Brazilian personal-income-tax rules for financial-asset gains,
applied "as if sold today":
  * renda_fixa (fixed income, including Tesouro Direto): regressive table by
    days held (Lei 11.033/2004).
  * fii (fundos imobiliários): 20% flat, no exemption threshold.
  * acoes_etfs_cripto (stocks/ETFs/crypto): 15% flat. There's a monthly
    exemption (R$20k/month in stock sales, R$35k/month in crypto sales) this
    estimator does NOT compute — it has no visibility into actual monthly
    sale volume, only "if this position were sold today" — so it's surfaced
    as an informational note instead of a number.

Always an estimate, never tax advice — see IREstimateResponse.disclaimer.
"""
from datetime import date
from typing import Optional

from app.schemas.asset import AssetRead
from app.schemas.ir_estimate import IRAssetEstimate, IREstimateResponse

STOCK_ETF_CRYPTO_NOTE = (
    "Isenção de R$20.000/mês em vendas de ações (R$35.000/mês para cripto) não é considerada aqui — "
    "esta estimativa assume a venda total da posição hoje, não seu histórico de vendas do mês."
)


def regressive_rate_pct(days_held: int) -> float:
    """Regressive rate for renda fixa, by days held (Lei 11.033/2004)."""
    if days_held <= 180:
        return 22.5
    if days_held <= 360:
        return 20.0
    if days_held <= 720:
        return 17.5
    return 15.0


def estimate_asset(asset: AssetRead, *, today: Optional[date] = None) -> Optional[IRAssetEstimate]:
    """Estimate for a single asset, or None when not applicable: no
    tax_category (real_estate/vehicle/valuable/other), no gain, or —
    for renda_fixa specifically — no purchase_date to count days from."""
    if asset.tax_category is None:
        return None

    gain = asset.gain_loss_primary if asset.gain_loss_primary is not None else asset.gain_loss
    if gain is None or gain <= 0:
        return None

    today = today or date.today()
    days_held = (today - asset.purchase_date).days if asset.purchase_date else None

    if asset.tax_category == "renda_fixa":
        if days_held is None:
            return None
        rate = regressive_rate_pct(days_held)
        note = None
    elif asset.tax_category == "fii":
        rate = 20.0
        note = None
    elif asset.tax_category == "acoes_etfs_cripto":
        rate = 15.0
        note = STOCK_ETF_CRYPTO_NOTE
    else:  # pragma: no cover — tax_category is constrained to the 3 above
        return None

    return IRAssetEstimate(
        asset_id=asset.id,
        name=asset.name,
        ticker=asset.ticker,
        tax_category=asset.tax_category,
        gain=gain,
        purchase_date=asset.purchase_date,
        days_held=days_held,
        rate_pct=rate,
        estimated_tax=gain * rate / 100,
        note=note,
    )


def estimate_portfolio(assets: list[AssetRead], *, today: Optional[date] = None) -> IREstimateResponse:
    estimates = [
        estimate for asset in assets if (estimate := estimate_asset(asset, today=today)) is not None
    ]
    total = sum(e.estimated_tax for e in estimates)
    return IREstimateResponse(assets=estimates, total_estimated_tax=total)
