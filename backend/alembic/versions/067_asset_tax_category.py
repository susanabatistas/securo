"""add tax_category override to assets

Revision ID: 067
Revises: 066
Create Date: 2026-08-09

Nullable override for the IR (income tax) estimator's tax bucket
(renda_fixa/fii/acoes_etfs_cripto). NULL means "use the default derived
from type+ticker" (app/services/asset_classification.py) or "not
applicable" for non-securities types (real_estate/vehicle/valuable/other).
Purely additive, same pattern as migration 066.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "067"
down_revision: Union[str, None] = "066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("tax_category", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "tax_category")
