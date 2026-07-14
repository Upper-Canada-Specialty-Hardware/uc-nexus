"""Add manufacturer column to hardware_items (issue #231)

Captures the TITAN manufacturer read from each product's Material_List_Fields block, carried end to
end from the parser through finalize onto the HardwareItem row. Nullable, no backfill: existing rows
keep NULL and render blank.

Revision ID: 045
Revises: 044
Create Date: 2026-07-13
"""

import sqlalchemy as sa

from alembic import op

revision = "045"
down_revision = "044"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("hardware_items", sa.Column("manufacturer", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("hardware_items", "manufacturer")
