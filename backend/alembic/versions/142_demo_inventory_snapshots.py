"""demo inventory snapshots (issue #1638)

The legacy inventory export the demo company's warehouse is seeded from. Stored rather than committed: it
is the company's own data. No company column, so the demo reset leaves it in place.

Revision ID: 142
Revises: 141
Create Date: 2026-10-14
"""

import sqlalchemy as sa

from alembic import op

revision = "142"
down_revision = "141"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_inventory_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("rows", sa.JSON(), nullable=False),
        sa.Column("row_count", sa.Integer(), nullable=False),
        sa.Column("uploaded_by", sa.String(length=255), nullable=False),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("demo_inventory_snapshots")
