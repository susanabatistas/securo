import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.user import User
from app.providers.market_price import StockFundamentals


@pytest_asyncio.fixture
async def stock_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="Petrobras",
        type="stock",
        currency="BRL",
        valuation_method="market_price",
        ticker="PETR4.SA",
        units=Decimal("100"),
        last_price=Decimal("38.5"),
        last_price_at=date(2026, 8, 1),
        source="yfinance",
        position=0,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest_asyncio.fixture
async def real_estate_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(),
        user_id=test_user.id,
        name="House",
        type="real_estate",
        currency="BRL",
        valuation_method="manual",
        purchase_price=Decimal("300000"),
        position=0,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest.mark.asyncio
async def test_stock_checklist_success(client: AsyncClient, auth_headers, stock_asset: Asset):
    fake = AsyncMock()
    fake.get_stock_fundamentals = AsyncMock(
        return_value=StockFundamentals(
            sector="Energy",
            industry="Oil & Gas",
            roe_avg_pct=20.0,
            revenue_cagr_pct=8.0,
            profit_cagr_pct=5.0,
            net_debt_to_ebitda=1.2,
            years_available=5,
        )
    )
    with patch("app.api.assets.get_market_price_provider", return_value=fake):
        resp = await client.get(
            f"/api/assets/{stock_asset.id}/stock-checklist", headers=auth_headers
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["overall_status"] == "aprovado"
    assert body["symbol"] == "PETR4.SA"
    assert len(body["criteria"]) == 4
    fake.get_stock_fundamentals.assert_awaited_once_with("PETR4.SA", years=5)


@pytest.mark.asyncio
async def test_stock_checklist_respects_custom_thresholds(
    client: AsyncClient, auth_headers, stock_asset: Asset
):
    fake = AsyncMock()
    fake.get_stock_fundamentals = AsyncMock(
        return_value=StockFundamentals(
            sector=None,
            industry=None,
            roe_avg_pct=10.0,
            revenue_cagr_pct=8.0,
            profit_cagr_pct=5.0,
            net_debt_to_ebitda=1.2,
            years_available=3,
        )
    )
    with patch("app.api.assets.get_market_price_provider", return_value=fake):
        resp = await client.get(
            f"/api/assets/{stock_asset.id}/stock-checklist",
            headers=auth_headers,
            params={"roe_min": 5.0},
        )
    assert resp.status_code == 200
    roe = next(c for c in resp.json()["criteria"] if c["key"] == "roe")
    assert roe["status"] == "pass"


@pytest.mark.asyncio
async def test_stock_checklist_rejects_non_stock_asset(
    client: AsyncClient, auth_headers, real_estate_asset: Asset
):
    resp = await client.get(
        f"/api/assets/{real_estate_asset.id}/stock-checklist", headers=auth_headers
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_stock_checklist_404_for_unknown_asset(client: AsyncClient, auth_headers):
    resp = await client.get(f"/api/assets/{uuid.uuid4()}/stock-checklist", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_stock_checklist_surfaces_manual_override(
    client: AsyncClient, auth_headers, session: AsyncSession, stock_asset: Asset
):
    stock_asset.stock_checklist_status = "aprovado"
    session.add(stock_asset)
    await session.commit()

    fake = AsyncMock()
    fake.get_stock_fundamentals = AsyncMock(return_value=None)
    with patch("app.api.assets.get_market_price_provider", return_value=fake):
        resp = await client.get(
            f"/api/assets/{stock_asset.id}/stock-checklist", headers=auth_headers
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["overall_status"] == "nao_avaliado"
    assert body["manual_override"] == "aprovado"
