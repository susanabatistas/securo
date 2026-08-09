"""add stock_checklist_status override to assets

Revision ID: 066
Revises: 065
Create Date: 2026-08-08

Manual override for the automatic stock checklist verdict (aprovado/rever/
a_evitar). Nullable, additive column — NULL means "use the computed default"
(see app/services/stock_checklist_service.py). No backfill needed and no
existing column is touched.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "066"
down_revision: Union[str, None] = "065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("stock_checklist_status", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "stock_checklist_status")
