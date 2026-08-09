import uuid
from datetime import date
from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.providers.market_price import DividendEvent
from app.models.user import User


@pytest_asyncio.fixture
async def stock_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Petrobras", type="stock",
        currency="BRL", valuation_method="market_price", ticker="PETR4.SA",
        units=Decimal("100"), last_price=Decimal("30"), purchase_date=date(2026, 1, 1), position=0,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest_asyncio.fixture
async def fii_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="HGLG11", type="fund",
        currency="BRL", valuation_method="market_price", ticker="HGLG11.SA",
        units=Decimal("10"), last_price=Decimal("160"), purchase_date=date(2026, 1, 1), position=1,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest_asyncio.fixture
async def manual_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Casa", type="real_estate",
        currency="BRL", valuation_method="manual", purchase_price=Decimal("100000"), position=2,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest.mark.asyncio
async def test_preview_dividend_history_defaults_to_dividendo_for_stock(
    client: AsyncClient, auth_headers, stock_asset: Asset
):
    fake = AsyncMock()
    fake.get_dividend_history = AsyncMock(
        return_value=[
            DividendEvent(date=date(2026, 2, 1), amount=0.5),
            DividendEvent(date=date(2026, 3, 1), amount=0.6),
        ]
    )
    with patch("app.api.assets.get_market_price_provider", return_value=fake):
        resp = await client.get(f"/api/assets/{stock_asset.id}/income/fetch-preview", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["ticker"] == "PETR4.SA"
    assert len(data["candidates"]) == 2
    assert all(c["kind"] == "dividendo" for c in data["candidates"])
    fake.get_dividend_history.assert_awaited_once_with("PETR4.SA", since=date(2026, 1, 1))


@pytest.mark.asyncio
async def test_preview_dividend_history_defaults_to_rendimento_for_fund(
    client: AsyncClient, auth_headers, fii_asset: Asset
):
    fake = AsyncMock()
    fake.get_dividend_history = AsyncMock(return_value=[DividendEvent(date=date(2026, 2, 1), amount=1.1)])
    with patch("app.api.assets.get_market_price_provider", return_value=fake):
        resp = await client.get(f"/api/assets/{fii_asset.id}/income/fetch-preview", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["candidates"][0]["kind"] == "rendimento"


@pytest.mark.asyncio
async def test_preview_dividend_history_excludes_already_logged_dates(
    client: AsyncClient, auth_headers, stock_asset: Asset
):
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 0.5, "date": "2026-02-01"},
    )
    fake = AsyncMock()
    fake.get_dividend_history = AsyncMock(
        return_value=[
            DividendEvent(date=date(2026, 2, 1), amount=0.5),  # already logged
            DividendEvent(date=date(2026, 3, 1), amount=0.6),  # new
        ]
    )
    with patch("app.api.assets.get_market_price_provider", return_value=fake):
        resp = await client.get(f"/api/assets/{stock_asset.id}/income/fetch-preview", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert len(data["candidates"]) == 1
    assert data["candidates"][0]["date"] == "2026-03-01"


@pytest.mark.asyncio
async def test_preview_dividend_history_422_for_manual_asset(
    client: AsyncClient, auth_headers, manual_asset: Asset
):
    resp = await client.get(f"/api/assets/{manual_asset.id}/income/fetch-preview", headers=auth_headers)
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_preview_dividend_history_404_for_unknown_asset(client: AsyncClient, auth_headers):
    resp = await client.get(f"/api/assets/{uuid.uuid4()}/income/fetch-preview", headers=auth_headers)
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_apply_dividend_history_creates_income_rows(
    client: AsyncClient, auth_headers, stock_asset: Asset
):
    resp = await client.post(
        f"/api/assets/{stock_asset.id}/income/fetch-apply",
        headers=auth_headers,
        json={"candidates": [
            {"date": "2026-02-01", "amount": 0.5, "kind": "dividendo"},
            {"date": "2026-03-01", "amount": 0.6, "kind": "dividendo"},
        ]},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert len(data) == 2
    assert all(row["source"] == "yfinance" for row in data)
