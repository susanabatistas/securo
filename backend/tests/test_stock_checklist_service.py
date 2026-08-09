from unittest.mock import AsyncMock

import pytest

from app.providers.market_price import StockFundamentals
from app.services import stock_checklist_service


def _fundamentals(**overrides) -> StockFundamentals:
    base = dict(
        sector="Energy",
        industry="Oil & Gas",
        roe_avg_pct=20.0,
        revenue_cagr_pct=8.0,
        profit_cagr_pct=5.0,
        net_debt_to_ebitda=1.2,
        years_available=5,
    )
    base.update(overrides)
    return StockFundamentals(**base)


def test_all_criteria_pass_is_aprovado():
    result = stock_checklist_service.build_result("PETR4.SA", _fundamentals())
    assert result.overall_status == "aprovado"
    assert all(c.status == "pass" for c in result.criteria)
    assert result.sector == "Energy"
    assert result.industry == "Oil & Gas"


def test_one_failing_criterion_is_rever():
    result = stock_checklist_service.build_result(
        "PETR4.SA", _fundamentals(roe_avg_pct=5.0)  # below default 15% threshold
    )
    assert result.overall_status == "rever"
    roe = next(c for c in result.criteria if c.key == "roe")
    assert roe.status == "fail"


def test_two_failing_criteria_is_a_evitar():
    result = stock_checklist_service.build_result(
        "PETR4.SA",
        _fundamentals(roe_avg_pct=5.0, net_debt_to_ebitda=4.0),  # both below/above threshold
    )
    assert result.overall_status == "a_evitar"


def test_missing_single_datum_is_not_evaluated_for_that_criterion_only():
    result = stock_checklist_service.build_result(
        "PETR4.SA", _fundamentals(net_debt_to_ebitda=None)
    )
    net_debt = next(c for c in result.criteria if c.key == "net_debt_to_ebitda")
    assert net_debt.status == "not_evaluated"
    # The other three criteria still pass -> overall still aprovado.
    assert result.overall_status == "aprovado"


def test_no_fundamentals_at_all_is_nao_avaliado():
    result = stock_checklist_service.build_result("PETR4.SA", None)
    assert result.overall_status == "nao_avaliado"
    assert result.criteria == []
    assert result.years_used == 0


def test_thresholds_are_adjustable_not_hardcoded():
    fundamentals = _fundamentals(roe_avg_pct=10.0)
    default_result = stock_checklist_service.build_result("PETR4.SA", fundamentals)
    assert next(c for c in default_result.criteria if c.key == "roe").status == "fail"

    lenient_result = stock_checklist_service.build_result(
        "PETR4.SA", fundamentals, roe_min=5.0
    )
    assert next(c for c in lenient_result.criteria if c.key == "roe").status == "pass"


def test_manual_override_is_passed_through_untouched():
    result = stock_checklist_service.build_result(
        "PETR4.SA", _fundamentals(roe_avg_pct=5.0), manual_override="aprovado"
    )
    # The computed verdict still reflects the numbers — the override is
    # surfaced separately for the caller (API/UI) to decide which wins.
    assert result.overall_status == "rever"
    assert result.manual_override == "aprovado"


@pytest.mark.asyncio
async def test_evaluate_calls_provider_and_builds_result():
    provider = AsyncMock()
    provider.get_stock_fundamentals = AsyncMock(return_value=_fundamentals())
    result = await stock_checklist_service.evaluate(provider, "PETR4.SA", years=3)
    provider.get_stock_fundamentals.assert_awaited_once_with("PETR4.SA", years=3)
    assert result.overall_status == "aprovado"


@pytest.mark.asyncio
async def test_evaluate_provider_without_fundamentals_support_returns_nao_avaliado():
    class NoFundamentalsProvider:
        pass

    result = await stock_checklist_service.evaluate(NoFundamentalsProvider(), "PETR4.SA")
    assert result.overall_status == "nao_avaliado"
