"""purchase_orders.ordered_at holds a calendar date, not an instant (issue #701)

What this column holds is GP's document date off the PO header: a calendar date, with no time of day
in it and no zone it belongs to. A datetime column was the wrong type for that. Every value landed as
midnight, and a zoneless datetime is read by the frontend as a UTC instant, so midnight printed as
the previous evening anywhere behind UTC and every Order Date on the PO table was a day early.

The conversion loses nothing: every stored value was already midnight.

Revision ID: 115
Revises: 114
Create Date: 2026-09-17
"""

from alembic import op

revision = "115"
down_revision = "114"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TABLE purchase_orders ALTER COLUMN ordered_at TYPE date USING ordered_at::date")


def downgrade() -> None:
    op.execute(
        "ALTER TABLE purchase_orders ALTER COLUMN ordered_at TYPE timestamp without time zone "
        "USING ordered_at::timestamp"
    )
