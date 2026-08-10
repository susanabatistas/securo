import io
import json
import uuid
import zipfile
from datetime import date
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.asset import Asset
from app.models.asset_group import AssetGroup
from app.models.asset_income import AssetIncome
from app.models.asset_transaction import AssetTransaction
from app.models.asset_value import AssetValue
from app.models.category import Category
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace


@pytest.mark.asyncio
async def test_backup_unauthenticated(client: AsyncClient):
    response = await client.get("/api/export/backup")
    assert response.status_code == 401


@pytest.mark.asyncio
async def test_backup_empty(client: AsyncClient, auth_headers):
    response = await client.get("/api/export/backup", headers=auth_headers)
    assert response.status_code == 200
    assert response.headers["content-type"] == "application/zip"

    buf = io.BytesIO(response.content)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert "metadata.json" in names
        assert "accounts.json" in names
        assert "transactions.json" in names

        metadata = json.loads(zf.read("metadata.json"))
        assert metadata["format_version"] == "1.1"
        assert "export_date" in metadata
        for count in metadata["entity_counts"].values():
            assert count == 0


@pytest.mark.asyncio
async def test_backup_with_data(
    client: AsyncClient,
    auth_headers,
    test_account: Account,
    test_transactions: list[Transaction],
    test_categories: list[Category],
    test_rules: list[Rule],
):
    response = await client.get("/api/export/backup", headers=auth_headers)
    assert response.status_code == 200

    # Verify Content-Disposition header contains filename
    disposition = response.headers.get("content-disposition", "")
    assert "securo-backup-" in disposition
    assert ".zip" in disposition

    buf = io.BytesIO(response.content)
    with zipfile.ZipFile(buf) as zf:
        expected_files = [
            "accounts.json",
            "transactions.json",
            "categories.json",
            "category_groups.json",
            "rules.json",
            "recurring_transactions.json",
            "budgets.json",
            "asset_groups.json",
            "assets.json",
            "asset_values.json",
            "asset_transactions.json",
            "asset_income.json",
            "import_logs.json",
            "metadata.json",
        ]
        for fname in expected_files:
            assert fname in zf.namelist(), f"{fname} missing from ZIP"

        # Verify entity counts match
        metadata = json.loads(zf.read("metadata.json"))
        counts = metadata["entity_counts"]
        assert counts["accounts"] == 1
        assert counts["transactions"] == len(test_transactions)
        assert counts["categories"] == len(test_categories)
        assert counts["rules"] == len(test_rules)

        # Verify JSON content is parseable and has expected fields
        accounts = json.loads(zf.read("accounts.json"))
        assert len(accounts) == 1
        assert accounts[0]["name"] == "Conta Corrente"

        transactions = json.loads(zf.read("transactions.json"))
        assert len(transactions) == len(test_transactions)
        # Verify UUIDs are serialized as strings
        assert isinstance(transactions[0]["id"], str)
        # Verify dates are serialized as ISO strings
        assert isinstance(transactions[0]["date"], str)
        # Verify decimals are serialized as strings
        assert isinstance(transactions[0]["amount"], str)


@pytest.mark.asyncio
async def test_backup_with_assets(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user: User,
):
    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, name="Export Asset",
        type="other", currency="BRL", purchase_price=Decimal("1000"),
    )
    session.add(asset)
    await session.flush()
    av = AssetValue(
        id=uuid.uuid4(), asset_id=asset.id,
        amount=Decimal("1200"), date=date.today(),
    )
    session.add(av)
    await session.commit()

    resp = await client.get("/api/export/backup", headers=auth_headers)
    assert resp.status_code == 200
    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        assets = json.loads(zf.read("assets.json"))
        asset_values = json.loads(zf.read("asset_values.json"))
        assert len(assets) >= 1
        assert len(asset_values) >= 1


@pytest.mark.asyncio
async def test_backup_metadata_structure(client: AsyncClient, auth_headers):
    resp = await client.get("/api/export/backup", headers=auth_headers)
    assert resp.status_code == 200
    assert "application/zip" in resp.headers.get("content-type", "")
    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        names = zf.namelist()
        assert "metadata.json" in names
        meta = json.loads(zf.read("metadata.json"))
        assert "export_date" in meta
        assert meta["format_version"] == "1.1"
        assert "entity_counts" in meta


@pytest.mark.asyncio
async def test_backup_includes_investment_ledger_entities(
    client: AsyncClient, auth_headers, session: AsyncSession, test_user: User, test_workspace: Workspace,
):
    """asset_groups, asset_transactions, and asset_income were previously
    missing from the backup entirely — a restore would have dropped every
    wallet, the buy/sell ledger the cost basis is derived from, and all
    dividend history."""
    group = AssetGroup(
        id=uuid.uuid4(), user_id=test_user.id, name="ETFs",
    )
    session.add(group)
    await session.flush()

    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="PETR4.SA", type="stock", currency="BRL", ticker="PETR4.SA",
        valuation_method="market_price", group_id=group.id,
    )
    session.add(asset)
    await session.flush()

    tx = AssetTransaction(
        id=uuid.uuid4(), asset_id=asset.id, workspace_id=test_workspace.id,
        kind="buy", quantity=Decimal("10"), price=Decimal("30.00"), date=date.today(),
    )
    session.add(tx)

    income = AssetIncome(
        id=uuid.uuid4(), asset_id=asset.id, workspace_id=test_workspace.id,
        kind="dividendo", amount=Decimal("12.50"), date=date.today(),
    )
    session.add(income)
    await session.commit()

    resp = await client.get("/api/export/backup", headers=auth_headers)
    assert resp.status_code == 200
    buf = io.BytesIO(resp.content)
    with zipfile.ZipFile(buf) as zf:
        groups = json.loads(zf.read("asset_groups.json"))
        transactions = json.loads(zf.read("asset_transactions.json"))
        incomes = json.loads(zf.read("asset_income.json"))

        assert len(groups) == 1
        assert groups[0]["name"] == "ETFs"

        assert len(transactions) == 1
        assert transactions[0]["kind"] == "buy"
        assert isinstance(transactions[0]["quantity"], str)  # Decimal -> str

        assert len(incomes) == 1
        assert incomes[0]["kind"] == "dividendo"
        assert isinstance(incomes[0]["amount"], str)  # Decimal -> str
