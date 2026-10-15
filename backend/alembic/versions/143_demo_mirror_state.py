"""demo mirror state (issue #1657)

What the demo copy of UBC is built from and how its last build and nightly sync went. No company column,
so a rebuild of the demo company leaves it in place.

Revision ID: 143
Revises: 142
Create Date: 2026-10-15
"""

import sqlalchemy as sa

from alembic import op

revision = "143"
down_revision = "142"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_mirror_state",
        sa.Column("key", sa.String(length=50), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("demo_mirror_state")
