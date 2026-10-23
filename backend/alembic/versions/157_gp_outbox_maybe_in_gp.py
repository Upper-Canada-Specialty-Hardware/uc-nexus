"""gp write outbox: a sticky flag for a write that may already be in GP (issue #1849)

Since #1389 a keyed receipt that timed out, or whose link died with it on the wire, goes back on the
queue rather than failing as ambiguous. When such a row later exhausts its attempts or is cancelled,
nothing on it said GP may already hold the receipt, so its draft went back for approval under a new key
and a second approval posted the receipt to GP twice. `maybe_in_gp` records it, and is never cleared.

Backfilled true on every row that already failed as ambiguous, and on every row whose last attempt
timed out: the only traces a row carried of it until now. An earlier timeout a later attempt overwrote
left none.
Downgrade drops the column.

Revision ID: 157
Revises: 156
Create Date: 2026-10-22
"""

import sqlalchemy as sa

from alembic import op

revision = "157"
down_revision = "156"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "gp_write_outbox",
        sa.Column("maybe_in_gp", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE gp_write_outbox SET maybe_in_gp = true "
        "WHERE failure_kind = 'ambiguous' OR last_error_code = 'RELAY_TIMEOUT'"
    )


def downgrade() -> None:
    op.drop_column("gp_write_outbox", "maybe_in_gp")
