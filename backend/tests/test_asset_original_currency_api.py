import uuid
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.fx_rate import FxRate
from app.models.user import User


@pytest.mark.asyncio
async def test_foreign_currency_asset_exposes_purchase_price_primary_and_fx_rate(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User
):
    purchase_date = date(2026, 1, 15)
    session.add(
        FxRate(
            id=uuid.uuid4(), base_currency="USD", quote_currency="BRL",
            date=purchase_date, rate=Decimal("5.00"), source="test",
        )
    )
    await session.commit()

    response = await client.post(
        "/api/assets",
        headers=auth_headers,
        json={
            "name": "Apple Inc.",
            "type": "stock",
            "currency": "USD",
            "purchase_date": purchase_date.isoformat(),
            "purchase_price": 1000,  # USD
            "current_value": 1200,
        },
    )
    assert response.status_code == 201, response.text
    asset_id = response.json()["id"]

    detail = await client.get(f"/api/assets/{asset_id}", headers=auth_headers)
    assert detail.status_code == 200
    data = detail.json()
    assert data["currency"] == "USD"
    assert data["purchase_price"] == 1000.0
    # Stamped at the historical (purchase-date) rate, not a live one.
    assert data["purchase_price_primary"] == 5000.0
    assert data["fx_rate_used"] == 5.0

    listed = await client.get("/api/assets", headers=auth_headers)
    assert listed.status_code == 200
    listed_asset = next(a for a in listed.json() if a["id"] == asset_id)
    assert listed_asset["purchase_price_primary"] == 5000.0
    assert listed_asset["fx_rate_used"] == 5.0


@pytest.mark.asyncio
async def test_same_currency_asset_has_null_fx_fields(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User
):
    response = await client.post(
        "/api/assets",
        headers=auth_headers,
        json={
            "name": "Casa",
            "type": "real_estate",
            "currency": "BRL",
            "purchase_price": 300000,
            "current_value": 350000,
        },
    )
    assert response.status_code == 201, response.text
    data = response.json()
    # fx_rate_used is only meaningful (and only computed) when a conversion
    # actually happened — same-currency assets have nothing to show here.
    assert data["fx_rate_used"] is None
    # purchase_price_primary is still stamped 1:1 (stamp_primary_amount's
    # own same-currency identity case), which is fine — it's a legitimate
    # value, just not the interesting "moeda original" case.
    assert data["purchase_price_primary"] == 300000.0
