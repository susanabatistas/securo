"""add recurring weekend adjustment policy (issue #496)

Revision ID: 070
Revises: 069
Create Date: 2026-08-05

Existing recurring transactions retain their current behavior through the
server-side ``none`` default. The check constraint keeps persisted values in
sync with the API's validated policy set.

Renumbered from upstream's 066 to 070 when merging upstream/main into this
fork — 066 was already taken here by an unrelated fork-only migration
(asset_classification), and the fork's chain by this point already extends
to 069.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "070"
down_revision: Union[str, None] = "069"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_CONSTRAINT_NAME = "ck_recurring_transactions_weekend_adjustment"


def upgrade() -> None:
    op.add_column(
        "recurring_transactions",
        sa.Column(
            "weekend_adjustment",
            sa.String(length=20),
            nullable=False,
            server_default=sa.text("'none'"),
        ),
    )
    op.create_check_constraint(
        _CONSTRAINT_NAME,
        "recurring_transactions",
        "weekend_adjustment IN ('none', 'previous_friday', 'next_monday')",
    )


def downgrade() -> None:
    op.drop_constraint(
        _CONSTRAINT_NAME,
        "recurring_transactions",
        type_="check",
    )
    op.drop_column("recurring_transactions", "weekend_adjustment")
