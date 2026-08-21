"""add original transaction description

Revision ID: 075
Revises: 074
Create Date: 2026-08-13

Renumbered from upstream's 071 to 075 when merging upstream/main into this
fork — 071 was already taken here by an unrelated fork-only migration
(transfer_amount_explicit).
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "075"
down_revision: Union[str, None] = "074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "transactions",
        sa.Column("original_description", sa.String(length=500), nullable=True),
    )
    op.add_column(
        "transactions",
        sa.Column(
            "description_is_rule_managed",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "description_is_rule_managed")
    op.drop_column("transactions", "original_description")
