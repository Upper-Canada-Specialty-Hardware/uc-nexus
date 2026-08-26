"""Add notes to receive_drafts and receive_records (#632)

Revision ID: 099
Revises: 098
Create Date: 2026-08-26

Free-text remark entered while counting a delivery ("box crushed", "short 2 per slip"). Lives on the
draft while it waits on a Warehouse Manager and is copied onto the ReceiveRecord at approval, so the
remark survives after the draft's lifecycle ends. Nexus-only - nothing here reaches GP. Nullable;
existing rows simply have no remark. Downgrade drops both columns.
"""

import sqlalchemy as sa

from alembic import op

revision = "099"
down_revision = "098"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("receive_drafts", sa.Column("notes", sa.Text(), nullable=True))
    op.add_column("receive_records", sa.Column("notes", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("receive_records", "notes")
    op.drop_column("receive_drafts", "notes")
