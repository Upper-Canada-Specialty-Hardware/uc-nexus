"""units ordered past the latest schedule are surplus, not required (issue #1491)

- hardware_items.beyond_schedule_quantity: the part of a row's quantity the latest hardware schedule
  no longer asks for. A schedule replace keeps every row already on a PO (#1123), so when a revision
  lowers or drops a product that was already ordered, the ordered units stay and this records how
  many of them are past the new schedule. Hardware status reports them as surplus instead of required.
- A check keeps it between 0 and the row's own quantity.

Existing rows start at 0; the next finalize of each project restates it.

Revision ID: 154
Revises: 153
Create Date: 2026-10-20
"""

import sqlalchemy as sa

from alembic import op

revision = "154"
down_revision = "153"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "hardware_items",
        sa.Column("beyond_schedule_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_hardware_items_beyond_schedule_within_quantity",
        "hardware_items",
        "beyond_schedule_quantity >= 0 AND beyond_schedule_quantity <= item_quantity",
    )


def downgrade() -> None:
    op.drop_constraint("ck_hardware_items_beyond_schedule_within_quantity", "hardware_items", type_="check")
    op.drop_column("hardware_items", "beyond_schedule_quantity")
