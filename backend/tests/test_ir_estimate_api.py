import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.asset import Asset
from app.models.user import User


@pytest_asyncio.fixture
async def ir_assets(session: AsyncSession, test_user: User) -> list[Asset]:
    long_held_stock = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Petrobras", type="stock",
        currency="BRL", valuation_method="manual",
        purchase_date=date.today() - timedelta(days=800),
        purchase_price=Decimal("1000.00"), position=0,
    )
    fii = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="HGLG11", type="fund",
        currency="BRL", valuation_method="manual",
        purchase_date=date.today() - timedelta(days=400),
        purchase_price=Decimal("2000.00"), position=1,
    )
    no_gain = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Losing position", type="stock",
        currency="BRL", valuation_method="manual",
        purchase_date=date.today() - timedelta(days=100),
        purchase_price=Decimal("5000.00"), position=2,
    )
    not_applicable = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Car", type="vehicle",
        currency="BRL", valuation_method="manual",
        purchase_date=date.today() - timedelta(days=100),
        purchase_price=Decimal("100.00"), position=3,
    )
    already_sold = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Sold stock", type="stock",
        currency="BRL", valuation_method="manual",
        purchase_date=date.today() - timedelta(days=800),
        purchase_price=Decimal("100.00"), sell_date=date.today(), sell_price=Decimal("500.00"),
        position=4,
    )
    session.add_all([long_held_stock, fii, no_gain, not_applicable, already_sold])
    await session.commit()

    from app.models.asset_value import AssetValue

    for asset, current in [
        (long_held_stock, Decimal("1500.00")),  # +500 gain
        (fii, Decimal("2300.00")),  # +300 gain
        (no_gain, Decimal("4000.00")),  # -1000 loss
        (not_applicable, Decimal("110.00")),  # +10 gain, but not applicable
    ]:
        session.add(AssetValue(id=uuid.uuid4(), asset_id=asset.id, amount=current, date=date.today(), source="manual"))
    await session.commit()

    return [long_held_stock, fii, no_gain, not_applicable, already_sold]


@pytest.mark.asyncio
async def test_ir_estimate_includes_only_applicable_assets_with_gains(
    client: AsyncClient, auth_headers: dict, ir_assets: list[Asset]
):
    response = await client.get("/api/assets/ir-estimate", headers=auth_headers)
    assert response.status_code == 200, response.text
    data = response.json()

    assert data["applicable"] is True
    names = {a["name"] for a in data["assets"]}
    assert names == {"Petrobras", "HGLG11"}
    assert "estimativa" in data["disclaimer"].lower()

    petrobras = next(a for a in data["assets"] if a["name"] == "Petrobras")
    assert petrobras["tax_category"] == "acoes_etfs_cripto"
    assert petrobras["rate_pct"] == 15.0
    assert petrobras["estimated_tax"] == pytest.approx(75.0)
    assert petrobras["note"] is not None

    hglg = next(a for a in data["assets"] if a["name"] == "HGLG11")
    assert hglg["tax_category"] == "fii"
    assert hglg["rate_pct"] == 20.0
    assert hglg["estimated_tax"] == pytest.approx(60.0)
    assert hglg["note"] is None

    assert data["total_estimated_tax"] == pytest.approx(75.0 + 60.0)


@pytest.mark.asyncio
async def test_ir_estimate_empty_portfolio(client: AsyncClient, auth_headers: dict):
    response = await client.get("/api/assets/ir-estimate", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["assets"] == []
    assert data["total_estimated_tax"] == 0
    assert data["applicable"] is True


@pytest.mark.asyncio
async def test_ir_estimate_not_applicable_for_non_brl_primary_currency(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User, ir_assets: list[Asset]
):
    # BR tax rates only make sense against a BRL gain — nothing should be
    # computed (or leak a foreign-currency number under a "R$" disclaimer)
    # when the user's primary currency is something else.
    test_user.preferences = {**(test_user.preferences or {}), "currency_display": "USD"}
    session.add(test_user)
    await session.commit()

    response = await client.get("/api/assets/ir-estimate", headers=auth_headers)
    assert response.status_code == 200
    data = response.json()
    assert data["applicable"] is False
    assert data["assets"] == []
    assert data["total_estimated_tax"] == 0
