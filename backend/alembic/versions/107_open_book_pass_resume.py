"""Resume state for the mirror's open-book pass

Revision ID: 107
Revises: 106
Create Date: 2026-09-03

The incremental pass stops being one unbounded "re-read every open PO" request and becomes a walk of
keyset pages of GP_SYNC_READ_BATCH. UBC has 2,344 open POs; at 25 a page that is 94 requests, and a
restart partway through must not start the walk again from the beginning - it would spend the budget
re-reading what it already has and never reach the end.

`open_book_cursor` is where the walk is up to, null between passes. `open_pass_started_at` is when the
current walk began, and it is what makes closure detection survive a restart: a PO that is open in
Nexus and whose `gp_synced_at` is older than the walk's start was not in GP's open table this pass, so
it has closed, been voided, or moved to history. Holding that set in memory instead would mean a
restart could never finish a pass it did not start.

Both nullable, both null on every existing row, which is exactly "no walk in progress".
"""

import sqlalchemy as sa

from alembic import op

revision = "107"
down_revision = "106"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # String(17) matches backfill_cursor: a GP PONUMBER is char(17).
    op.add_column("gp_po_sync_state", sa.Column("open_book_cursor", sa.String(17), nullable=True))
    op.add_column("gp_po_sync_state", sa.Column("open_pass_started_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("gp_po_sync_state", "open_pass_started_at")
    op.drop_column("gp_po_sync_state", "open_book_cursor")
