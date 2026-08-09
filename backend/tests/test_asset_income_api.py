import uuid
from datetime import date
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.user import User


@pytest_asyncio.fixture
async def stock_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Petrobras", type="stock",
        currency="BRL", valuation_method="market_price", ticker="PETR4.SA",
        units=Decimal("100"), last_price=Decimal("30"), position=0,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest_asyncio.fixture
async def sold_asset(session: AsyncSession, test_user: User) -> Asset:
    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="VALE3 (vendido)", type="stock",
        currency="BRL", valuation_method="market_price", ticker="VALE3.SA",
        units=Decimal("0"), sell_date=date(2026, 1, 1), position=1,
    )
    session.add(asset)
    await session.commit()
    await session.refresh(asset)
    return asset


@pytest.mark.asyncio
async def test_add_income_manual(client: AsyncClient, auth_headers, stock_asset: Asset):
    resp = await client.post(
        f"/api/assets/{stock_asset.id}/income",
        headers=auth_headers,
        json={"kind": "dividendo", "amount": 45.0, "date": "2026-03-10"},
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["kind"] == "dividendo"
    assert data["amount"] == 45.0
    assert data["ticker"] == "PETR4.SA"
    assert data["source"] == "manual"
    assert data["asset_sold"] is False


@pytest.mark.asyncio
async def test_add_income_allowed_on_sold_asset(client: AsyncClient, auth_headers, sold_asset: Asset):
    # Confirmed with the user: a dividend can be logged for a position held
    # during the period, even after it's since been sold.
    resp = await client.post(
        f"/api/assets/{sold_asset.id}/income",
        headers=auth_headers,
        json={"kind": "dividendo", "amount": 12.0, "date": "2025-12-01"},
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["asset_sold"] is True


@pytest.mark.asyncio
async def test_add_income_404_for_unknown_asset(client: AsyncClient, auth_headers):
    resp = await client.post(
        f"/api/assets/{uuid.uuid4()}/income",
        headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2026-01-01"},
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_list_asset_income(client: AsyncClient, auth_headers, stock_asset: Asset):
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2026-01-01"},
    )
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "jcp", "amount": 5.0, "date": "2026-02-01"},
    )
    resp = await client.get(f"/api/assets/{stock_asset.id}/income", headers=auth_headers)
    assert resp.status_code == 200
    assert len(resp.json()) == 2


@pytest.mark.asyncio
async def test_list_workspace_income_filters_by_year(client: AsyncClient, auth_headers, stock_asset: Asset):
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2025-06-01"},
    )
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 20.0, "date": "2026-06-01"},
    )
    resp_2026 = await client.get("/api/assets/income", headers=auth_headers, params={"year": 2026})
    assert resp_2026.status_code == 200
    assert len(resp_2026.json()) == 1
    assert resp_2026.json()[0]["amount"] == 20.0

    resp_all = await client.get("/api/assets/income", headers=auth_headers)
    assert len(resp_all.json()) == 2


@pytest.mark.asyncio
async def test_income_summary(client: AsyncClient, auth_headers, stock_asset: Asset):
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2026-03-05"},
    )
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 15.0, "date": "2026-03-20"},
    )
    resp = await client.get("/api/assets/income/summary", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] == 25.0
    assert len(data["months"]) == 1
    assert data["months"][0]["month"] == "2026-03"
    assert data["months"][0]["total"] == 25.0


@pytest.mark.asyncio
async def test_update_and_delete_income(client: AsyncClient, auth_headers, stock_asset: Asset):
    create = await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2026-01-01"},
    )
    income_id = create.json()["id"]

    updated = await client.patch(
        f"/api/assets/income/{income_id}", headers=auth_headers, json={"amount": 99.0},
    )
    assert updated.status_code == 200
    assert updated.json()["amount"] == 99.0

    deleted = await client.delete(f"/api/assets/income/{income_id}", headers=auth_headers)
    assert deleted.status_code == 204

    listing = await client.get(f"/api/assets/{stock_asset.id}/income", headers=auth_headers)
    assert listing.json() == []


@pytest.mark.asyncio
async def test_income_mixed_currency_is_converted_not_summed_raw(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user: User, stock_asset: Asset
):
    """Regression: a user with both BR (BRL) and international (USD)
    holdings saw the Proventos chart/total add a USD dividend as if it
    were that many BRL — the aggregation never converted currencies before
    summing. test_user's primary currency is BRL (see conftest)."""
    from app.models.fx_rate import FxRate

    usd_asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Apple", type="stock",
        currency="USD", valuation_method="market_price", ticker="AAPL",
        units=Decimal("10"), last_price=Decimal("200"), position=1,
    )
    session.add(usd_asset)
    session.add(FxRate(
        id=uuid.uuid4(), base_currency="USD", quote_currency="BRL",
        date=date(2026, 3, 1), rate=Decimal("5.00"), source="test",
    ))
    await session.commit()

    # 10 BRL (native) + 10 USD (native) — naively summed raw that's "20",
    # but the USD leg is worth 50 BRL at the seeded rate, so the correct
    # primary-currency total is 60.
    await client.post(
        f"/api/assets/{stock_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2026-03-01"},
    )
    await client.post(
        f"/api/assets/{usd_asset.id}/income", headers=auth_headers,
        json={"kind": "dividendo", "amount": 10.0, "date": "2026-03-01"},
    )

    listing = await client.get("/api/assets/income", headers=auth_headers, params={"year": 2026})
    rows = {r["ticker"]: r for r in listing.json()}
    assert rows["AAPL"]["amount"] == 10.0
    assert rows["AAPL"]["amount_primary"] == 50.0  # converted at the seeded rate
    assert rows[stock_asset.ticker]["amount_primary"] == 10.0  # already BRL

    summary = await client.get("/api/assets/income/summary", headers=auth_headers, params={"year": 2026})
    data = summary.json()
    assert data["total"] == 60.0
    assert data["months"][0]["total"] == 60.0
