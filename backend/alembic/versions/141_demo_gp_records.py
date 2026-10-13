"""demo gp records (issue #1608)

The demo company's GP is simulated inside the backend. This table is what that simulation remembers:
the jobs, POs, receipts, buyers and customer addresses written to it, so a registered demo PO reads
back and a receipt posted against it shows up as received.

Revision ID: 141
Revises: 140
Create Date: 2026-10-13
"""

import sqlalchemy as sa

from alembic import op

revision = "141"
down_revision = "140"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "demo_gp_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("kind", sa.String(length=30), nullable=False),
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("data", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("kind", "key", name="uq_demo_gp_records_kind_key"),
    )


def downgrade() -> None:
    op.drop_table("demo_gp_records")
