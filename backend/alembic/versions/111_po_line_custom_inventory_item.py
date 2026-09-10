"""The catalog entry a PO line was added from

Revision ID: 111
Revises: 110
Create Date: 2026-09-10

Order As is a hardware schedule item's field: the schedule's name for a product can differ from the
vendor's, and Order As is where that translation lives. A line added from the non-schedule item
catalog (#454) has nothing to translate - it is already written the way the vendor sells it - so the
field does not apply to it at all.

Nothing on the line said which kind of item it was, so the PO detail modal had no way to tell the two
apart and offered Order As on both. `custom_inventory_item_id` is that answer, and it doubles as the
link back to the catalog entry the line came from.
"""

import sqlalchemy as sa

from alembic import op

revision = "111"
down_revision = "110"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "po_line_items",
        sa.Column(
            "custom_inventory_item_id",
            sa.Uuid(),
            sa.ForeignKey("custom_inventory_items.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("po_line_items", "custom_inventory_item_id")
