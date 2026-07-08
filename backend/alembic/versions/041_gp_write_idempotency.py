"""Idempotency ledger for the GP-first writes (issue #202 follow-up #1).

create_po / register_po_in_gp / create_receive push to GP via the relay before persisting the UC Nexus
record, so a client retry after a post-GP failure could double-post a GP receipt or reserve a duplicate
GP PO number. This table lets the resolver make the client-generated idempotency key a no-op on retry.

Revision ID: 041
Revises: 040
Create Date: 2026-07-07
"""

import sqlalchemy as sa

from alembic import op

revision = "041"
down_revision = "040"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "gp_write_idempotency",
        sa.Column("key", sa.String(), nullable=False),
        sa.Column("op", sa.String(), nullable=False),
        sa.Column("relay_result", sa.JSON(), nullable=True),
        sa.Column("result_id", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("gp_write_idempotency")
