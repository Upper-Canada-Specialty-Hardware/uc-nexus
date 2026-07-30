"""Drop per-buyer cost-code designation (#216 partial rollback)

Revision ID: 074
Revises: 073
Create Date: 2026-07-30

`buyer_assignments.cost_codes` held the subset of GP cost codes a buyer was allowed to use, and the
register-PO dropdown showed only that subset of the job's live codes. The premise was wrong: GP has
no per-job notion of "the right cost codes" - `WS_Inactive` is unused in practice (0 inactive rows
across all of UBC and TUBC), so every job carries its full division template and all of it is valid.
The subset was hand-maintained Nexus config, and in practice it hid valid codes from purchasers and
blocked legitimate registrations.

Buyer authorization itself is unchanged: a buyer still needs an assignment row and still may only
order for the projects it lists. Only the cost-code column goes.

`downgrade()` recreates the column with an empty-list default. The designations themselves are not
recoverable - they existed nowhere else - which is accepted: they were config to be re-entered, and
the only production values were a two-code list nobody wants back.
"""

import sqlalchemy as sa

from alembic import op

revision = "074"
down_revision = "073"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("buyer_assignments", "cost_codes")


def downgrade() -> None:
    # server_default fills existing rows; the model has no server default, so drop it again after.
    op.add_column(
        "buyer_assignments",
        sa.Column("cost_codes", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
    )
    op.alter_column("buyer_assignments", "cost_codes", server_default=None)
