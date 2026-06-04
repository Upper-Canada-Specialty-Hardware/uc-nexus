"""Relax inventory_locations FK columns + add stock_item_id link for allocations from stock

Revision ID: 029
Revises: 028
Create Date: 2026-06-04
"""

import sqlalchemy as sa

from alembic import op

revision = "029"
down_revision = "028"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Make existing FK columns nullable — stock-allocated rows have no backing PO line item
    op.alter_column(
        "inventory_locations",
        "po_line_item_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )
    op.alter_column(
        "inventory_locations",
        "receive_line_item_id",
        existing_type=sa.Uuid(),
        nullable=True,
    )

    # 2. Add stock_item_id column linking back to the stock_items row this allocation came from
    op.add_column(
        "inventory_locations",
        sa.Column(
            "stock_item_id",
            sa.Uuid(),
            sa.ForeignKey("stock_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_inventory_locations_stock_item",
        "inventory_locations",
        ["stock_item_id"],
    )

    # 3. CHECK constraint: every row has either a PO origin OR a stock origin (or both, if reused)
    op.create_check_constraint(
        "ck_inventory_locations_has_origin",
        "inventory_locations",
        "(po_line_item_id IS NOT NULL AND receive_line_item_id IS NOT NULL) OR stock_item_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_inventory_locations_has_origin", "inventory_locations", type_="check")
    op.drop_index("ix_inventory_locations_stock_item", table_name="inventory_locations")
    op.drop_column("inventory_locations", "stock_item_id")
    op.alter_column(
        "inventory_locations",
        "receive_line_item_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
    op.alter_column(
        "inventory_locations",
        "po_line_item_id",
        existing_type=sa.Uuid(),
        nullable=False,
    )
