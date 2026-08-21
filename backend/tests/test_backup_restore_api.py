"""Round-trip tests: build real data, call GET /api/export/backup to get a
real zip, then feed that same zip into /restore/preview and /restore —
exercises the two endpoints against exactly what the backup endpoint
actually produces, instead of hand-crafted fixture zips that could drift
from the real format."""
import io
import uuid
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from httpx import AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.account import Account
from app.models.asset import Asset
from app.models.asset_group import AssetGroup
from app.models.asset_income import AssetIncome
from app.models.asset_transaction import AssetTransaction
from app.models.bank_connection import BankConnection
from app.models.payee import Payee
from app.models.transaction import Transaction
from app.models.user import User
from app.models.workspace import Workspace, WorkspaceMember


async def _download_backup(client: AsyncClient, auth_headers: dict) -> bytes:
    resp = await client.get("/api/export/backup", headers=auth_headers)
    assert resp.status_code == 200
    return resp.content


@pytest.mark.asyncio
async def test_restore_preview_unauthenticated(client: AsyncClient):
    resp = await client.post("/api/export/restore/preview", files={"file": ("b.zip", b"junk", "application/zip")})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_restore_unauthenticated(client: AsyncClient):
    resp = await client.post("/api/export/restore", files={"file": ("b.zip", b"junk", "application/zip")})
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_restore_preview_rejects_garbage_file(client: AsyncClient, auth_headers: dict):
    resp = await client.post(
        "/api/export/restore/preview",
        headers=auth_headers,
        files={"file": ("not-a-zip.zip", b"this is not a zip file", "application/zip")},
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_restore_preview_rejects_zip_without_metadata(client: AsyncClient, auth_headers: dict):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("accounts.json", "[]")
    resp = await client.post(
        "/api/export/restore/preview",
        headers=auth_headers,
        files={"file": ("no-metadata.zip", buf.getvalue(), "application/zip")},
    )
    assert resp.status_code == 422
    assert "metadata" in resp.json()["detail"].lower()


@pytest.mark.asyncio
async def test_restore_preview_matches_backup_counts_and_writes_nothing(
    client: AsyncClient, auth_headers: dict, session: AsyncSession,
    test_account: Account, test_transactions: list[Transaction],
):
    content = await _download_backup(client, auth_headers)

    workspace_count_before = (await session.execute(select(func.count()).select_from(Workspace))).scalar()

    resp = await client.post(
        "/api/export/restore/preview",
        headers=auth_headers,
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["entity_counts"]["accounts"] == 1
    assert body["entity_counts"]["transactions"] == len(test_transactions)
    assert body["format_version"] == "1.2"

    workspace_count_after = (await session.execute(select(func.count()).select_from(Workspace))).scalar()
    assert workspace_count_after == workspace_count_before


@pytest.mark.asyncio
async def test_restore_creates_new_workspace_with_matching_data(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User,
    test_account: Account, test_transactions: list[Transaction],
):
    content = await _download_backup(client, auth_headers)

    resp = await client.post(
        "/api/export/restore",
        headers=auth_headers,
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    new_workspace = resp.json()
    assert new_workspace["id"] != str(test_account.workspace_id)
    assert new_workspace["role"] == "owner"

    new_ws_id = uuid.UUID(new_workspace["id"])

    # The restoring user is an owner member of the new workspace.
    member = (
        await session.execute(
            select(WorkspaceMember).where(
                WorkspaceMember.workspace_id == new_ws_id, WorkspaceMember.user_id == test_user.id,
            )
        )
    ).scalar_one_or_none()
    assert member is not None
    assert member.role == "owner"

    restored_accounts = (
        await session.execute(select(Account).where(Account.workspace_id == new_ws_id))
    ).scalars().all()
    assert len(restored_accounts) == 1
    # Every entity gets a brand new id on restore (see backup_restore_service
    # docstring) — restoring into the same database the backup came from
    # would otherwise collide with the still-existing original's primary key.
    assert restored_accounts[0].id != test_account.id
    assert restored_accounts[0].name == test_account.name

    restored_txs = (
        await session.execute(select(Transaction).where(Transaction.workspace_id == new_ws_id))
    ).scalars().all()
    assert len(restored_txs) == len(test_transactions)
    # Cross-reference remapped to point at the *restored* account, not the
    # original — both got new, but linked, ids.
    assert all(tx.account_id == restored_accounts[0].id for tx in restored_txs)


@pytest.mark.asyncio
async def test_restore_preserves_asset_group_and_ledger_references(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User, test_workspace: Workspace,
):
    group = AssetGroup(id=uuid.uuid4(), user_id=test_user.id, name="ETFs")
    session.add(group)
    await session.flush()

    asset = Asset(
        id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_workspace.id,
        name="PETR4.SA", type="stock", currency="BRL", ticker="PETR4.SA",
        valuation_method="market_price", group_id=group.id,
    )
    session.add(asset)
    await session.flush()

    session.add(AssetTransaction(
        id=uuid.uuid4(), asset_id=asset.id, workspace_id=test_workspace.id,
        kind="buy", quantity=Decimal("10"), price=Decimal("30.00"), date=date.today(),
    ))
    session.add(AssetIncome(
        id=uuid.uuid4(), asset_id=asset.id, workspace_id=test_workspace.id,
        kind="dividendo", amount=Decimal("12.50"), date=date.today(),
    ))
    await session.commit()

    content = await _download_backup(client, auth_headers)
    resp = await client.post(
        "/api/export/restore",
        headers=auth_headers,
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    new_ws_id = uuid.UUID(resp.json()["id"])

    restored_group = (
        await session.execute(select(AssetGroup).where(AssetGroup.workspace_id == new_ws_id))
    ).scalar_one()
    assert restored_group.id != group.id  # fresh id, not the original
    assert restored_group.name == "ETFs"

    restored_asset = (
        await session.execute(select(Asset).where(Asset.workspace_id == new_ws_id))
    ).scalar_one()
    assert restored_asset.id != asset.id
    # group_id remapped to point at the *restored* group's new id.
    assert restored_asset.group_id == restored_group.id

    restored_tx = (
        await session.execute(select(AssetTransaction).where(AssetTransaction.workspace_id == new_ws_id))
    ).scalar_one()
    assert restored_tx.asset_id == restored_asset.id
    assert restored_tx.kind == "buy"

    restored_income = (
        await session.execute(select(AssetIncome).where(AssetIncome.workspace_id == new_ws_id))
    ).scalar_one()
    assert restored_income.asset_id == restored_asset.id
    assert restored_income.kind == "dividendo"


@pytest.mark.asyncio
async def test_restore_nulls_out_connection_and_payee_references(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User,
    test_account: Account,  # already wired to a BankConnection via connection_id
):
    payee = Payee(id=uuid.uuid4(), user_id=test_user.id, workspace_id=test_account.workspace_id, name="Uber")
    session.add(payee)
    await session.flush()

    tx = Transaction(
        id=uuid.uuid4(), user_id=test_user.id, account_id=test_account.id,
        payee_id=payee.id, description="UBER TRIP", amount=Decimal("25.50"),
        date=date.today(), type="debit", source="manual",
    )
    session.add(tx)
    await session.commit()

    assert test_account.connection_id is not None  # sanity: fixture actually set it

    content = await _download_backup(client, auth_headers)
    resp = await client.post(
        "/api/export/restore",
        headers=auth_headers,
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    new_ws_id = uuid.UUID(resp.json()["id"])

    restored_account = (
        await session.execute(select(Account).where(Account.workspace_id == new_ws_id))
    ).scalar_one()
    assert restored_account.connection_id is None  # BankConnection was never in the backup

    restored_tx = (
        await session.execute(
            select(Transaction).where(Transaction.workspace_id == new_ws_id, Transaction.description == "UBER TRIP")
        )
    ).scalar_one()
    assert restored_tx.payee_id is None  # Payee was never in the backup
    assert restored_tx.account_id == restored_account.id  # non-nulled FK still remapped correctly


@pytest.mark.asyncio
async def test_restore_ignores_workspace_id_and_user_id_from_the_file(
    client: AsyncClient, auth_headers: dict, session: AsyncSession, test_user: User, test_account: Account,
):
    """Even though the backup's JSON carries the *original* workspace_id
    and user_id on every row, the restored rows must belong to the brand
    new workspace and the restoring user — never the values in the file."""
    content = await _download_backup(client, auth_headers)
    resp = await client.post(
        "/api/export/restore",
        headers=auth_headers,
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert resp.status_code == 201, resp.text
    new_ws_id = uuid.UUID(resp.json()["id"])
    assert new_ws_id != test_account.workspace_id

    restored_account = (
        await session.execute(select(Account).where(Account.workspace_id == new_ws_id))
    ).scalar_one()
    assert restored_account.id != test_account.id  # fresh id, not the file's original
    assert restored_account.user_id == test_user.id


@pytest.mark.asyncio
async def test_restore_reads_a_password_protected_backup(
    client: AsyncClient, auth_headers: dict, test_account: Account,
):
    """parse_backup_zip opens with pyzipper.AESZipFile precisely so it can
    read a backup encrypted via POST /api/export/backup — the encryption
    feature and the restore feature were built independently and this is
    the one thing that actually links them."""
    resp = await client.post(
        "/api/export/backup", json={"password": "correct horse battery"}, headers=auth_headers,
    )
    assert resp.status_code == 200
    content = resp.content

    # Wrong/missing password -> 422, not a crash or a silent partial read.
    no_password = await client.post(
        "/api/export/restore/preview",
        headers=auth_headers,
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert no_password.status_code == 422

    wrong_password = await client.post(
        "/api/export/restore/preview",
        headers=auth_headers,
        data={"password": "wrong horse battery"},
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert wrong_password.status_code == 422

    preview = await client.post(
        "/api/export/restore/preview",
        headers=auth_headers,
        data={"password": "correct horse battery"},
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["entity_counts"]["accounts"] == 1

    restore = await client.post(
        "/api/export/restore",
        headers=auth_headers,
        data={"password": "correct horse battery"},
        files={"file": ("backup.zip", content, "application/zip")},
    )
    assert restore.status_code == 201, restore.text
