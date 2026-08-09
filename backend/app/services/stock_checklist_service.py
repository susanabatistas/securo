"""Deterministic, threshold-based checklist for individual stocks.

No AI/LLM — every verdict is a rule applied to numbers already fetched from
the market-price provider (see `app/providers/market_price.py`'s
`get_stock_fundamentals`). Thresholds are function parameters with sane
defaults, not constants baked into the logic, so callers (the API layer)
can expose them as adjustable inputs.

Only applies to individual stocks — never ETFs, funds, FIIs, fixed income,
or crypto (enforced by the caller, not here).
"""
from typing import Optional

from app.providers.market_price import MarketPriceProvider, StockFundamentals
from app.schemas.stock_checklist import StockChecklistCriterion, StockChecklistResult

DEFAULT_ROE_MIN_PCT = 15.0
DEFAULT_REVENUE_CAGR_MIN_PCT = 0.0
DEFAULT_PROFIT_CAGR_MIN_PCT = 0.0
DEFAULT_NET_DEBT_EBITDA_MAX = 2.0
DEFAULT_YEARS = 5


def _criterion(
    key: str, value: Optional[float], threshold: float, *, higher_is_better: bool
) -> StockChecklistCriterion:
    if value is None:
        return StockChecklistCriterion(key=key, value=None, threshold=threshold, status="not_evaluated")
    passed = value >= threshold if higher_is_better else value <= threshold
    return StockChecklistCriterion(
        key=key, value=value, threshold=threshold, status="pass" if passed else "fail"
    )


def _overall_status(criteria: list[StockChecklistCriterion]) -> str:
    evaluated = [c for c in criteria if c.status != "not_evaluated"]
    if not evaluated:
        return "nao_avaliado"
    failed = [c for c in evaluated if c.status == "fail"]
    if not failed:
        return "aprovado"
    if len(failed) == 1:
        return "rever"
    return "a_evitar"


def build_result(
    symbol: str,
    fundamentals: Optional[StockFundamentals],
    *,
    manual_override: Optional[str] = None,
    roe_min: float = DEFAULT_ROE_MIN_PCT,
    revenue_cagr_min: float = DEFAULT_REVENUE_CAGR_MIN_PCT,
    profit_cagr_min: float = DEFAULT_PROFIT_CAGR_MIN_PCT,
    net_debt_ebitda_max: float = DEFAULT_NET_DEBT_EBITDA_MAX,
) -> StockChecklistResult:
    """Pure — applies thresholds to already-fetched fundamentals. Split out
    from `evaluate` so the rule logic is testable without a provider."""
    if fundamentals is None:
        return StockChecklistResult(
            symbol=symbol,
            criteria=[],
            overall_status="nao_avaliado",
            years_used=0,
            manual_override=manual_override,
        )

    criteria = [
        _criterion("roe", fundamentals.roe_avg_pct, roe_min, higher_is_better=True),
        _criterion(
            "revenue_cagr", fundamentals.revenue_cagr_pct, revenue_cagr_min, higher_is_better=True
        ),
        _criterion(
            "profit_cagr", fundamentals.profit_cagr_pct, profit_cagr_min, higher_is_better=True
        ),
        _criterion(
            "net_debt_to_ebitda",
            fundamentals.net_debt_to_ebitda,
            net_debt_ebitda_max,
            higher_is_better=False,
        ),
    ]

    return StockChecklistResult(
        symbol=symbol,
        sector=fundamentals.sector,
        industry=fundamentals.industry,
        criteria=criteria,
        overall_status=_overall_status(criteria),
        years_used=fundamentals.years_available,
        manual_override=manual_override,
    )


async def evaluate(
    provider: MarketPriceProvider,
    symbol: str,
    *,
    manual_override: Optional[str] = None,
    roe_min: float = DEFAULT_ROE_MIN_PCT,
    revenue_cagr_min: float = DEFAULT_REVENUE_CAGR_MIN_PCT,
    profit_cagr_min: float = DEFAULT_PROFIT_CAGR_MIN_PCT,
    net_debt_ebitda_max: float = DEFAULT_NET_DEBT_EBITDA_MAX,
    years: int = DEFAULT_YEARS,
) -> StockChecklistResult:
    get_fundamentals = getattr(provider, "get_stock_fundamentals", None)
    fundamentals = await get_fundamentals(symbol, years=years) if get_fundamentals else None
    return build_result(
        symbol,
        fundamentals,
        manual_override=manual_override,
        roe_min=roe_min,
        revenue_cagr_min=revenue_cagr_min,
        profit_cagr_min=profit_cagr_min,
        net_debt_ebitda_max=net_debt_ebitda_max,
    )
