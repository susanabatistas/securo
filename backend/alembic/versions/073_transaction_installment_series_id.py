"""add stable ids to manual installment series

Revision ID: 073
Revises: 072
Create Date: 2026-08-12

Manual installment rows created by the series endpoint share one UUID. The
existing installment metadata remains available for provider sync deduplication
and for legacy rows that predate this migration.

Renumbered from upstream's 069 to 073 when merging upstream/main into this
fork — 069 was already taken here by an unrelated fork-only migration
(target_allocation).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "073"
down_revision: Union[str, None] = "072"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column(
            "installment_series_id",
            postgresql.UUID(as_uuid=True),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_transactions_installment_series_id",
        "transactions",
        ["installment_series_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_transactions_installment_series_id",
        table_name="transactions",
    )
    op.drop_column("transactions", "installment_series_id")
