from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.auth import current_active_user
from app.core.database import get_async_session
from app.core.workspace_context import WorkspaceContext, current_workspace
from app.models.account import Account
from app.models.asset import Asset
from app.models.asset_group import AssetGroup
from app.models.asset_income import AssetIncome
from app.models.asset_transaction import AssetTransaction
from app.models.asset_value import AssetValue
from app.models.budget import Budget
from app.models.category import Category
from app.models.category_group import CategoryGroup
from app.models.import_log import ImportLog
from app.models.recurring_transaction import RecurringTransaction
from app.models.rule import Rule
from app.models.transaction import Transaction
from app.models.user import User
from app.schemas.export import BackupRequest
from app.schemas.workspace import WorkspaceRead
from app.services import backup_restore_service
from app.services.backup_service import build_backup_archive

router = APIRouter(prefix="/api/export", tags=["export"])


def _serialize(obj) -> dict:
    """Convert a SQLAlchemy model instance to a JSON-serializable dict."""
    d = {}
    for col in obj.__table__.columns:
        val = getattr(obj, col.key)
        if isinstance(val, UUID):
            val = str(val)
        elif isinstance(val, (datetime, date)):
            val = val.isoformat()
        elif isinstance(val, Decimal):
            val = str(val)
        d[col.key] = val
    return d


async def _collect(ctx: WorkspaceContext, session: AsyncSession) -> dict[str, object]:
    """Every entity in the workspace, keyed by the file it becomes.

    Backup is scoped to one workspace at a time — users with multiple
    workspaces back each one up separately. AssetValue inherits its
    workspace from its Asset and is filtered transitively.
    """
    ws_id = ctx.workspace.id

    accounts = (await session.execute(select(Account).where(Account.workspace_id == ws_id))).scalars().all()
    transactions = (await session.execute(select(Transaction).where(Transaction.workspace_id == ws_id))).scalars().all()
    categories = (await session.execute(select(Category).where(Category.workspace_id == ws_id))).scalars().all()
    category_groups = (await session.execute(select(CategoryGroup).where(CategoryGroup.workspace_id == ws_id))).scalars().all()
    rules = (await session.execute(select(Rule).where(Rule.workspace_id == ws_id))).scalars().all()
    recurring_transactions = (await session.execute(select(RecurringTransaction).where(RecurringTransaction.workspace_id == ws_id))).scalars().all()
    budgets = (await session.execute(select(Budget).where(Budget.workspace_id == ws_id))).scalars().all()
    asset_groups = (await session.execute(select(AssetGroup).where(AssetGroup.workspace_id == ws_id))).scalars().all()
    assets = (await session.execute(select(Asset).where(Asset.workspace_id == ws_id))).scalars().all()
    import_logs = (await session.execute(select(ImportLog).where(ImportLog.workspace_id == ws_id))).scalars().all()
    asset_transactions = (
        (await session.execute(select(AssetTransaction).where(AssetTransaction.workspace_id == ws_id))).scalars().all()
    )
    asset_income = (
        (await session.execute(select(AssetIncome).where(AssetIncome.workspace_id == ws_id))).scalars().all()
    )

    asset_ids = [a.id for a in assets]
    if asset_ids:
        asset_values = (await session.execute(select(AssetValue).where(AssetValue.asset_id.in_(asset_ids)))).scalars().all()
    else:
        asset_values = []

    entities = {
        "accounts": accounts,
        "transactions": transactions,
        "categories": categories,
        "category_groups": category_groups,
        "rules": rules,
        "recurring_transactions": recurring_transactions,
        "budgets": budgets,
        "asset_groups": asset_groups,
        "assets": assets,
        "asset_values": asset_values,
        "asset_transactions": asset_transactions,
        "asset_income": asset_income,
        "import_logs": import_logs,
    }

    files: dict[str, object] = {}
    entity_counts = {}
    for name, rows in entities.items():
        serialized = [_serialize(r) for r in rows]
        entity_counts[name] = len(serialized)
        files[f"{name}.json"] = serialized

    files["metadata.json"] = {
        "export_date": datetime.now(timezone.utc).isoformat(),
        # 1.1 added asset_groups/asset_transactions/asset_income. 1.2
        # adds the workspace's own settings (kind/currency/locale/
        # icon/color) — restore needs these to recreate a workspace
        # that matches the original instead of falling back to
        # generic defaults.
        "format_version": "1.2",
        "workspace_id": str(ws_id),
        "workspace_name": ctx.workspace.name,
        "workspace_kind": ctx.workspace.kind,
        "workspace_default_currency": ctx.workspace.default_currency,
        "workspace_locale": ctx.workspace.locale,
        "workspace_icon": ctx.workspace.icon,
        "workspace_color": ctx.workspace.color,
        "entity_counts": entity_counts,
    }
    return files


def _as_download(archive: bytes) -> StreamingResponse:
    today = date.today().isoformat()
    return StreamingResponse(
        iter([archive]),
        media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="securo-backup-{today}.zip"'},
    )


@router.get("/backup")
async def backup(
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """Export every entity in the current workspace as a JSON zip."""
    return _as_download(build_backup_archive(await _collect(ctx, session)))


@router.post("/backup")
async def backup_protected(
    body: BackupRequest,
    ctx: WorkspaceContext = Depends(current_workspace),
    session: AsyncSession = Depends(get_async_session),
):
    """The same archive, encrypted with AES-256 when a password is given.

    A POST because the password belongs in a body: a query string is written
    to browser history, proxy logs and server access logs. Securo never stores
    the password and cannot recover the archive without it.
    """
    password = body.password.get_secret_value() if body.password else None
    return _as_download(build_backup_archive(await _collect(ctx, session), password))


@router.post("/restore/preview")
async def restore_preview(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    _: User = Depends(current_active_user),
):
    """Validate a backup zip and summarize what it contains, without
    writing anything to the database. Raises 422 with a clear message for
    anything that isn't a readable Securo backup of a supported version —
    including a missing/wrong password on an encrypted archive."""
    content = await file.read()
    try:
        bundle = backup_restore_service.parse_backup_zip(content, password)
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    meta = bundle.metadata
    return {
        "workspace_name": meta.get("workspace_name"),
        "export_date": meta.get("export_date"),
        "format_version": meta.get("format_version"),
        "entity_counts": {name: len(rows) for name, rows in bundle.entities.items()},
    }


@router.post("/restore", response_model=WorkspaceRead, status_code=status.HTTP_201_CREATED)
async def restore(
    file: UploadFile = File(...),
    password: str | None = Form(None),
    user: User = Depends(current_active_user),
    session: AsyncSession = Depends(get_async_session),
):
    """Restore a backup zip into a brand new workspace (never merges into
    an existing one — see backup_restore_service module docstring). The
    caller becomes that workspace's owner."""
    content = await file.read()
    try:
        bundle = backup_restore_service.parse_backup_zip(content, password)
        workspace = await backup_restore_service.restore_backup(session, bundle, user)
    except ValueError as e:
        await session.rollback()
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(e))

    await session.commit()
    item = WorkspaceRead.model_validate(workspace)
    item.role = "owner"
    return item
