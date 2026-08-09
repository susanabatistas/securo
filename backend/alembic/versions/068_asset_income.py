"""add asset_income table for dividend/JCP/rendimento receipts

Revision ID: 068
Revises: 067
Create Date: 2026-08-09

New table, deliberately separate from `asset_transactions`: income receipts
don't change a holding's units/average_price/cost basis, so they never
enter the buy/sell ledger replay (asset_transaction_service._recompute).
Fed by the B3 CSV importer's Dividendo/JCP/Rendimento rows and by manual
entry (the only path for international assets, which never appear in a B3
statement). No existing table or column is touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "068"
down_revision: Union[str, None] = "067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "asset_income",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "asset_id",
            sa.UUID(),
            sa.ForeignKey("assets.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "workspace_id",
            sa.UUID(),
            sa.ForeignKey("workspaces.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),  # dividendo, jcp, rendimento, outro
        sa.Column("amount", sa.Numeric(precision=15, scale=2), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual"),
        sa.Column("external_id", sa.String(255), nullable=True),
        sa.Column("notes", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()")),
    )
    op.create_index("ix_asset_income_asset_id", "asset_income", ["asset_id"])
    op.create_index("ix_asset_income_workspace_id", "asset_income", ["workspace_id"])
    op.create_index("ix_asset_income_date", "asset_income", ["date"])


def downgrade() -> None:
    op.drop_index("ix_asset_income_date", table_name="asset_income")
    op.drop_index("ix_asset_income_workspace_id", table_name="asset_income")
    op.drop_index("ix_asset_income_asset_id", table_name="asset_income")
    op.drop_table("asset_income")
