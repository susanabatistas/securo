from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Optional

import pytest
from sqlalchemy import select

from app.models.asset import Asset
from app.models.asset_income import AssetIncome
from app.models.asset_transaction import AssetTransaction
from app.providers.market_price import MarketPriceProvider
from app.schemas.asset import MarketSymbolMatch, MarketSymbolQuote
from app.services.b3_import_service import B3IncomeRow, B3Row, apply_b3_rows, parse_b3_csv


class _FakeProvider(MarketPriceProvider):
    name = "fake"

    def __init__(self, quotes: dict[str, MarketSymbolQuote]):
        self._quotes = quotes

    async def search(self, query: str, limit: int = 20) -> list[MarketSymbolMatch]:
        return []

    async def get_quote(self, symbol: str) -> Optional[MarketSymbolQuote]:
        return self._quotes.get(symbol.upper())


def _quote(symbol: str, price: float, currency: str = "BRL") -> MarketSymbolQuote:
    return MarketSymbolQuote(symbol=symbol, name=f"{symbol} SA", exchange="SAO", currency=currency, price=price, quote_type="EQUITY")


@pytest.mark.asyncio
async def test_apply_b3_rows_creates_ledger_transactions(session, test_workspace, test_user):
    provider = _FakeProvider({"PETR4.SA": _quote("PETR4.SA", 30.0)})
    rows = [
        B3Row(ticker="PETR4.SA", product="PETR4 - PETROBRAS", kind="buy", quantity=Decimal("100"), price=Decimal("28.50"), date=date(2026, 3, 1)),
        B3Row(ticker="PETR4.SA", product="PETR4 - PETROBRAS", kind="buy", quantity=Decimal("50"), price=Decimal("30.00"), date=date(2026, 3, 15)),
        B3Row(ticker="PETR4.SA", product="PETR4 - PETROBRAS", kind="sell", quantity=Decimal("30"), price=Decimal("32.00"), date=date(2026, 3, 20)),
    ]
    result = await apply_b3_rows(session, test_workspace.id, test_user.id, rows, market_provider=provider)

    assert result.applied_count == 3
    assert result.errors == []

    asset = (await session.execute(
        select(Asset).where(Asset.workspace_id == test_workspace.id, Asset.ticker == "PETR4.SA")
    )).scalar_one()
    assert asset.units == 120  # 100 + 50 - 30

    txs = (await session.execute(
        select(AssetTransaction).where(AssetTransaction.asset_id == asset.id)
    )).scalars().all()
    assert len(txs) == 3
    assert all(tx.source == "import" for tx in txs)


@pytest.mark.asyncio
async def test_apply_b3_rows_reports_sell_without_matching_holding(session, test_workspace, test_user):
    rows = [
        B3Row(ticker="XPTO11.SA", product="XPTO11 - XPTO", kind="sell", quantity=Decimal("10"), price=Decimal("50"), date=date(2026, 3, 1)),
    ]
    result = await apply_b3_rows(session, test_workspace.id, test_user.id, rows)
    assert result.applied_count == 0
    assert len(result.errors) == 1
    assert result.errors[0].reason == "venda sem posição encontrada"


@pytest.mark.asyncio
async def test_apply_b3_rows_continues_after_one_row_fails(session, test_workspace, test_user):
    provider = _FakeProvider({"VALE3.SA": _quote("VALE3.SA", 60.0)})
    rows = [
        B3Row(ticker="VALE3.SA", product="VALE3 - VALE", kind="buy", quantity=Decimal("10"), price=Decimal("60"), date=date(2026, 3, 1)),
        # Oversell — should fail, but not block the earlier buy from applying.
        B3Row(ticker="VALE3.SA", product="VALE3 - VALE", kind="sell", quantity=Decimal("999"), price=Decimal("60"), date=date(2026, 3, 2)),
    ]
    result = await apply_b3_rows(session, test_workspace.id, test_user.id, rows, market_provider=provider)
    assert result.applied_count == 1
    assert len(result.errors) == 1

    asset = (await session.execute(
        select(Asset).where(Asset.workspace_id == test_workspace.id, Asset.ticker == "VALE3.SA")
    )).scalar_one()
    assert asset.units == 10


@pytest.mark.asyncio
async def test_apply_b3_rows_applies_br_ticker_override_for_fii(session, test_workspace, test_user):
    provider = _FakeProvider({"HGLG11.SA": _quote("HGLG11.SA", 160.0)})
    rows = [
        B3Row(ticker="HGLG11.SA", product="HGLG11 - CSHG LOGISTICA", kind="buy", quantity=Decimal("10"), price=Decimal("155"), date=date(2026, 3, 1)),
    ]
    result = await apply_b3_rows(session, test_workspace.id, test_user.id, rows, market_provider=provider)
    assert result.applied_count == 1

    asset = (await session.execute(
        select(Asset).where(Asset.workspace_id == test_workspace.id, Asset.ticker == "HGLG11.SA")
    )).scalar_one()
    assert asset.type == "fund"


@pytest.mark.asyncio
async def test_apply_b3_rows_records_income_after_trades(session, test_workspace, test_user):
    provider = _FakeProvider({"PETR4.SA": _quote("PETR4.SA", 30.0)})
    rows = [B3Row(ticker="PETR4.SA", product="PETR4 - PETROBRAS", kind="buy", quantity=Decimal("100"), price=Decimal("28.50"), date=date(2026, 3, 1))]
    income_rows = [B3IncomeRow(ticker="PETR4.SA", product="PETR4 - PETROBRAS", kind="dividendo", amount=Decimal("45.00"), date=date(2026, 3, 10))]

    result = await apply_b3_rows(session, test_workspace.id, test_user.id, rows, income_rows=income_rows, market_provider=provider)
    assert result.applied_count == 1
    assert result.income_applied_count == 1
    assert result.errors == []

    asset = (await session.execute(
        select(Asset).where(Asset.workspace_id == test_workspace.id, Asset.ticker == "PETR4.SA")
    )).scalar_one()
    income = (await session.execute(
        select(AssetIncome).where(AssetIncome.asset_id == asset.id)
    )).scalar_one()
    assert income.amount == Decimal("45.00")
    assert income.kind == "dividendo"
    assert income.source == "import"


@pytest.mark.asyncio
async def test_apply_b3_rows_records_income_for_sold_position(session, test_workspace, test_user):
    # Confirmed with the user: a dividend earned while still holding a
    # position must still be recordable after the same import sells it out.
    provider = _FakeProvider({"ITSA4.SA": _quote("ITSA4.SA", 10.0)})
    rows = [
        B3Row(ticker="ITSA4.SA", product="ITSA4 - ITAUSA", kind="buy", quantity=Decimal("100"), price=Decimal("9"), date=date(2026, 1, 1)),
        B3Row(ticker="ITSA4.SA", product="ITSA4 - ITAUSA", kind="sell", quantity=Decimal("100"), price=Decimal("11"), date=date(2026, 3, 1)),
    ]
    income_rows = [B3IncomeRow(ticker="ITSA4.SA", product="ITSA4 - ITAUSA", kind="dividendo", amount=Decimal("15.00"), date=date(2026, 2, 1))]

    result = await apply_b3_rows(session, test_workspace.id, test_user.id, rows, income_rows=income_rows, market_provider=provider)
    assert result.applied_count == 2
    assert result.income_applied_count == 1
    assert result.errors == []

    asset = (await session.execute(
        select(Asset).where(Asset.workspace_id == test_workspace.id, Asset.ticker == "ITSA4.SA")
    )).scalar_one()
    assert asset.units == 0
    income = (await session.execute(
        select(AssetIncome).where(AssetIncome.asset_id == asset.id)
    )).scalar_one()
    assert income.amount == Decimal("15.00")


@pytest.mark.asyncio
async def test_apply_b3_rows_reports_income_without_matching_asset(session, test_workspace, test_user):
    income_rows = [B3IncomeRow(ticker="XPTO4.SA", product="XPTO4 - XPTO", kind="dividendo", amount=Decimal("5.00"), date=date(2026, 1, 1))]
    result = await apply_b3_rows(session, test_workspace.id, test_user.id, [], income_rows=income_rows)
    assert result.income_applied_count == 0
    assert len(result.errors) == 1
    assert result.errors[0].reason == "provento sem posição encontrada"


@pytest.mark.asyncio
async def test_apply_b3_rows_matches_preexisting_dot_sa_asset_for_income_only_import(
    session, test_workspace, test_user
):
    """Regression: a real user's B3 export was proventos-only (no Compra
    rows) for tickers already held in Securo as "TICKER.SA" (the yfinance
    convention). Before _extract_ticker appended ".SA", the parser produced
    a bare "CMIG4" that never matched the existing "CMIG4.SA" asset, so
    100% of the proventos in that import failed with "provento sem posição
    encontrada" even though the holding was right there."""
    existing = Asset(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Cemig", type="stock", currency="BRL", valuation_method="market_price",
        ticker="CMIG4.SA", units=Decimal("18"), last_price=Decimal("10"), position=0,
    )
    session.add(existing)
    await session.commit()

    csv_text = (
        "Entrada/Saída;data;movimentacao;produto;Instituição;quantidade;preco;valor\n"
        "Credito;30/06/2026;juros sobre capital proprio;"
        "CMIG4 - CIA. ENERGETICA DE MINAS GERAIS- CEMIG;WARREN;18;R$0,10 ;R$1,59 \n"
    )
    parsed = parse_b3_csv(csv_text.encode("utf-8"))
    assert parsed.income_rows[0].ticker == "CMIG4.SA"

    result = await apply_b3_rows(
        session, test_workspace.id, test_user.id, parsed.rows, income_rows=parsed.income_rows,
    )
    assert result.income_applied_count == 1
    assert result.errors == []

    income = (await session.execute(
        select(AssetIncome).where(AssetIncome.asset_id == existing.id)
    )).scalar_one()
    assert income.amount == Decimal("1.59")


@pytest.mark.asyncio
async def test_apply_b3_rows_auto_detects_wallet_when_ticker_already_in_one(
    session, test_workspace, test_user
):
    """Regression #2 on the same real import: fixing the .SA suffix wasn't
    enough — the user's entire portfolio (45 assets) is organized into
    wallets (asset_groups), and the B3 dialog never asks "which wallet?"
    per import, so apply_b3_rows was called with group_id=None. The old
    lookup required an EXACT group_id match (None == None), so it still
    couldn't find a ticker sitting in any real wallet — every one of the
    user's 23 proventos failed a second time with "sem posição encontrada"
    even after the ticker matched correctly. Auto-detecting the wallet from
    the existing holding (when the caller didn't specify one) fixes this.
    """
    from app.models.asset_group import AssetGroup

    wallet = AssetGroup(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="XP", icon="wallet", color="#0EA5E9", position=0, source="manual",
    )
    session.add(wallet)
    await session.flush()
    existing = Asset(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Banco do Brasil", type="stock", currency="BRL", valuation_method="market_price",
        ticker="BBAS3.SA", units=Decimal("13"), last_price=Decimal("28"), position=0,
        group_id=wallet.id,
    )
    session.add(existing)
    await session.commit()

    income_rows = [B3IncomeRow(ticker="BBAS3.SA", product="BBAS3 - BANCO DO BRASIL", kind="jcp", amount=Decimal("2.32"), date=date(2026, 3, 5))]

    # group_id=None (default) — exactly what the import dialog sends today,
    # since it has no wallet picker.
    result = await apply_b3_rows(session, test_workspace.id, test_user.id, [], income_rows=income_rows)
    assert result.income_applied_count == 1
    assert result.errors == []

    income = (await session.execute(
        select(AssetIncome).where(AssetIncome.asset_id == existing.id)
    )).scalar_one()
    assert income.amount == Decimal("2.32")


@pytest.mark.asyncio
async def test_apply_b3_rows_explicit_group_id_still_wins_over_auto_detect(
    session, test_workspace, test_user
):
    from app.models.asset_group import AssetGroup

    wallet_a = AssetGroup(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Corretora A", icon="wallet", color="#0EA5E9", position=0, source="manual",
    )
    wallet_b = AssetGroup(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Corretora B", icon="wallet", color="#0EA5E9", position=1, source="manual",
    )
    session.add_all([wallet_a, wallet_b])
    await session.flush()
    asset_a = Asset(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Itausa A", type="stock", currency="BRL", valuation_method="market_price",
        ticker="ITSA4.SA", units=Decimal("10"), position=0, group_id=wallet_a.id,
    )
    asset_b = Asset(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="Itausa B", type="stock", currency="BRL", valuation_method="market_price",
        ticker="ITSA4.SA", units=Decimal("5"), position=1, group_id=wallet_b.id,
    )
    session.add_all([asset_a, asset_b])
    await session.commit()

    income_rows = [B3IncomeRow(ticker="ITSA4.SA", product="ITSA4 - ITAUSA", kind="dividendo", amount=Decimal("3.00"), date=date(2026, 3, 5))]
    result = await apply_b3_rows(
        session, test_workspace.id, test_user.id, [], income_rows=income_rows, group_id=wallet_b.id,
    )
    assert result.income_applied_count == 1
    income = (await session.execute(
        select(AssetIncome).where(AssetIncome.asset_id == asset_b.id)
    )).scalar_one_or_none()
    assert income is not None
    assert income.amount == Decimal("3.00")
