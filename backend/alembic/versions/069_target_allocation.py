"""add target_pct to asset_groups and assets

Revision ID: 069
Revises: 068
Create Date: 2026-08-09

Hierarchical rebalancing targets, two independent nullable percentages:
  * asset_groups.target_pct — a wallet's target share of the total
    portfolio (e.g. "ETFs wallet = 20% of everything").
  * assets.target_pct — an asset's target share of *its own wallet*, not
    of the total portfolio (e.g. "Asset A = 50% of the ETFs wallet"). Only
    meaningful for assets with a group_id; ignored (never validated at the
    DB level) for ungrouped assets.
Both nullable = "no target set" — the asset/wallet still shows up in the
allocation pie, just without a rebalance suggestion. No backfill, no
existing column touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "069"
down_revision: Union[str, None] = "068"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("asset_groups", sa.Column("target_pct", sa.Numeric(5, 2), nullable=True))
    op.add_column("assets", sa.Column("target_pct", sa.Numeric(5, 2), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "target_pct")
    op.drop_column("asset_groups", "target_pct")
