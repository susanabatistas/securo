"""Restore a workspace from a backup zip produced by GET /api/export/backup.

Always creates a brand new workspace — never merges into an existing one.
That avoids duplicate-data risk, but NOT id collisions on its own: restoring
a backup back into the same database it came from (e.g. "let me verify this
backup actually works") would try to insert a row with the same primary key
as the still-existing original, since `id` is unique across the whole
table, not per-workspace. So every entity gets a brand new `id`, and every
field that references another entity *in the same backup* (an asset's
wallet, a transaction's account, ...) is rewritten through an old-id ->
new-id map built as each stage is restored — see `restore_backup`. Only
FKs to tables that were never part of the backup at all (`connection_id`,
`payee_id`) are forced to NULL instead, since there's nothing to remap them
to.

`_deserialize` is the exact inverse of `_serialize` in app/api/export.py:
same three string-encoded types (UUID, Decimal, date/datetime), driven off
each column's `python_type` instead of a manual per-field mapping.
"""
from __future__ import annotations

import io
import json
import uuid
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

import pyzipper
from sqlalchemy.ext.asyncio import AsyncSession

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
from app.models.workspace import Workspace
from app.services import workspace_service

SUPPORTED_MAJOR_VERSION = 1
MAX_BACKUP_BYTES = 50 * 1024 * 1024  # 50MB — generous for a personal-finance backup

# (entity key == "<key>.json" in the zip, model, FK columns to null out
# because they point at a table that was never part of the backup).
# Order matters: every entity is inserted after everything it can point to
# (category_groups before categories, accounts before transactions, an
# asset's own group before the asset, the asset before its ledger/income).
RESTORE_ORDER: list[tuple[str, type, list[str]]] = [
    ("category_groups", CategoryGroup, []),
    ("categories", Category, []),
    ("accounts", Account, ["connection_id"]),
    ("asset_groups", AssetGroup, ["connection_id"]),
    ("assets", Asset, ["connection_id"]),
    ("asset_values", AssetValue, []),
    ("asset_transactions", AssetTransaction, []),
    ("asset_income", AssetIncome, []),
    ("import_logs", ImportLog, []),
    ("transactions", Transaction, ["payee_id"]),
    ("recurring_transactions", RecurringTransaction, []),
    ("budgets", Budget, []),
    ("rules", Rule, []),
]

# Fields (besides `id` itself) that hold a UUID reference to another
# entity that's also part of the backup. Remapped through the same
# old-id -> new-id table `id` goes through, in `restore_backup`, so the
# restored graph's internal relationships survive every row getting a
# fresh id. `Transaction.transfer_pair_id` isn't a DB-enforced FK (see
# the model) but is remapped anyway to keep transfer pairs linked; if its
# target isn't in this backup for some reason it just falls back to None
# rather than raising.
INTERNAL_FK_FIELDS: dict[type, list[str]] = {
    Category: ["group_id"],
    Asset: ["group_id"],
    AssetValue: ["asset_id"],
    AssetTransaction: ["asset_id"],
    AssetIncome: ["asset_id"],
    ImportLog: ["account_id"],
    Transaction: ["account_id", "category_id", "import_id", "transfer_pair_id"],
    RecurringTransaction: ["account_id", "category_id"],
    Budget: ["category_id"],
}


@dataclass(frozen=True)
class RestoreBundle:
    metadata: dict[str, Any]
    entities: dict[str, list[dict[str, Any]]] = field(default_factory=dict)


def _deserialize(model: type, row: dict[str, Any], overrides: dict[str, Any]) -> Any:
    """Build a model instance from a JSON-decoded row, converting each
    field back to the type its column expects (inverse of _serialize) and
    applying `overrides` last so callers can't accidentally trust
    workspace_id/user_id/connection_id values that came from the file."""
    kwargs: dict[str, Any] = {}
    for col in model.__table__.columns:
        key = col.key
        if key in overrides:
            kwargs[key] = overrides[key]
            continue
        if key not in row:
            continue
        value = row[key]
        if value is not None:
            try:
                py_type = col.type.python_type
            except NotImplementedError:
                py_type = None
            if py_type is uuid.UUID:
                value = uuid.UUID(value)
            elif py_type is Decimal:
                value = Decimal(value)
            elif py_type is datetime:
                value = datetime.fromisoformat(value)
            elif py_type is date:
                value = date.fromisoformat(value)
        kwargs[key] = value
    return model(**kwargs)


def parse_backup_zip(content: bytes, password: Optional[str] = None) -> RestoreBundle:
    """Validate and decode a backup zip without touching the database.
    Raises ValueError with a message safe to surface to the user for
    anything that isn't a readable Securo backup of a supported version —
    including a missing/wrong password on an AES-encrypted archive.

    Opened with pyzipper.AESZipFile rather than the stdlib zipfile: it
    transparently reads both a plain zip and one encrypted with
    build_backup_archive's AES-256 (setting a password is a no-op on a
    plain archive), so this one code path handles both without needing to
    sniff which kind was uploaded."""
    if not content:
        raise ValueError("empty file")
    if len(content) > MAX_BACKUP_BYTES:
        raise ValueError(f"backup file too large (max {MAX_BACKUP_BYTES // (1024 * 1024)}MB)")

    try:
        zf = pyzipper.AESZipFile(io.BytesIO(content))
    except pyzipper.BadZipFile as exc:
        raise ValueError("not a valid zip file") from exc
    if password:
        zf.setpassword(password.encode("utf-8"))

    with zf:
        names = set(zf.namelist())
        if "metadata.json" not in names:
            raise ValueError("missing metadata.json — this doesn't look like a Securo backup")
        try:
            metadata = json.loads(zf.read("metadata.json"))
        except json.JSONDecodeError as exc:
            raise ValueError("metadata.json is not valid JSON") from exc
        except RuntimeError as exc:
            # pyzipper raises RuntimeError (not a dedicated exception type)
            # for both "no password given" and "wrong password".
            raise ValueError("this backup is password-protected, or the password given is wrong") from exc

        version = str(metadata.get("format_version", ""))
        try:
            major = int(version.split(".")[0])
        except (ValueError, IndexError):
            major = None
        if major != SUPPORTED_MAJOR_VERSION:
            raise ValueError(f"unsupported backup format version: {version!r}")

        entities: dict[str, list[dict[str, Any]]] = {}
        for name, _model, _null_fields in RESTORE_ORDER:
            filename = f"{name}.json"
            if filename not in names:
                # Absent = a backup from an older format_version that
                # predates this entity — treated as "nothing to restore
                # here", not an error, so older backups still work.
                entities[name] = []
                continue
            try:
                rows = json.loads(zf.read(filename))
            except json.JSONDecodeError as exc:
                raise ValueError(f"{filename} is not valid JSON") from exc
            if not isinstance(rows, list):
                raise ValueError(f"{filename} does not contain a list")
            entities[name] = rows

    return RestoreBundle(metadata=metadata, entities=entities)


async def restore_backup(session: AsyncSession, bundle: RestoreBundle, creator: User) -> Workspace:
    """Create a new workspace from `bundle` and insert every entity into
    it. Does not commit — the caller controls the transaction boundary so
    a failure partway through rolls back the workspace too, leaving no
    partially-restored data behind."""
    meta = bundle.metadata
    workspace = await workspace_service.create_workspace(
        session,
        name=meta.get("workspace_name") or "Restored workspace",
        creator=creator,
        kind=meta.get("workspace_kind") or "personal",
        default_currency=meta.get("workspace_default_currency"),
        locale=meta.get("workspace_locale"),
        icon=meta.get("workspace_icon"),
        color=meta.get("workspace_color"),
        self_membership=True,
        seed_defaults=False,
    )

    # old id (as it appears in the JSON) -> freshly minted id, filled in
    # as each stage is processed. Shared across all stages so a later
    # stage (e.g. transactions) can resolve a reference to an earlier one
    # (e.g. accounts).
    id_map: dict[str, uuid.UUID] = {}

    for name, model, null_fields in RESTORE_ORDER:
        rows = bundle.entities.get(name, [])
        has_user_id = "user_id" in model.__table__.columns
        internal_fk_fields = INTERNAL_FK_FIELDS.get(model, [])

        # Pass 1: mint every new id for this stage up front. Needed for
        # same-stage self-references (Transaction.transfer_pair_id points
        # at another transaction in this same list) — without doing this
        # first, a transaction processed early wouldn't find its pair's
        # new id yet in pass 2 below.
        new_ids: dict[str, uuid.UUID] = {}
        for row in rows:
            old_id = row.get("id")
            if old_id is not None:
                new_id = uuid.uuid4()
                new_ids[old_id] = new_id
                id_map[old_id] = new_id

        try:
            for row in rows:
                overrides: dict[str, Any] = {"workspace_id": workspace.id}
                old_id = row.get("id")
                if old_id is not None:
                    overrides["id"] = new_ids[old_id]
                if has_user_id:
                    overrides["user_id"] = creator.id
                for field_name in null_fields:
                    overrides[field_name] = None
                for field_name in internal_fk_fields:
                    original = row.get(field_name)
                    overrides[field_name] = id_map.get(original) if original is not None else None
                session.add(_deserialize(model, row, overrides))
        except (TypeError, ValueError, InvalidOperation) as exc:
            raise ValueError(f"invalid data in {name}.json: {exc}") from exc

        # Flush after each stage so later entities' FKs (e.g. an asset's
        # group_id, a transaction's account_id) reference rows that
        # actually exist in the database yet, not just in the Python session.
        await session.flush()

    return workspace
