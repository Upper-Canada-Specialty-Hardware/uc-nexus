"""Shipment returns: ShipmentReturn + ShipmentReturnItem, RETURN audit action,
inventory_locations return origin (issue #89)

Revision ID: 035
Revises: 034
Create Date: 2026-06-23
"""

import sqlalchemy as sa

from alembic import op

revision = "035"
down_revision = "034"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. RETURN audit action (safe to add inside the transaction; not referenced until runtime)
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'RETURN'")

    # 2. return_disposition enum (created implicitly by the create_table below, per migration 030)
    return_disposition = sa.Enum(
        "RETURN_TO_PROJECT",
        "NON_STOCK",
        "RMA_DEFECTIVE",
        name="return_disposition",
    )

    # 3. shipment_returns header
    op.create_table(
        "shipment_returns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("packing_slip_id", sa.Uuid(), sa.ForeignKey("packing_slips.id"), nullable=False),
        sa.Column(
            "warehouse_id",
            sa.Uuid(),
            sa.ForeignKey("warehouses.id", ondelete="RESTRICT"),
            nullable=False,
        ),
        sa.Column("returned_by", sa.String(), nullable=False),
        sa.Column("returned_at", sa.DateTime(), nullable=False),
        sa.Column("reference", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_shipment_returns_packing_slip", "shipment_returns", ["packing_slip_id"])

    # 4. shipment_return_items (FKs target tables that already exist: packing_slip_items,
    #    inventory_locations, stock_items — so no circular create-order problem here)
    op.create_table(
        "shipment_return_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("shipment_return_id", sa.Uuid(), sa.ForeignKey("shipment_returns.id"), nullable=False),
        sa.Column("packing_slip_item_id", sa.Uuid(), sa.ForeignKey("packing_slip_items.id"), nullable=False),
        sa.Column("disposition", return_disposition, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=True),
        sa.Column("rma_reference", sa.String(100), nullable=True),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column(
            "resulting_inventory_location_id",
            sa.Uuid(),
            sa.ForeignKey("inventory_locations.id"),
            nullable=True,
        ),
        sa.Column("resulting_stock_item_id", sa.Uuid(), sa.ForeignKey("stock_items.id"), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity >= 1", name="ck_shipment_return_items_quantity_positive"),
    )
    op.create_index("ix_shipment_return_items_return", "shipment_return_items", ["shipment_return_id"])
    op.create_index(
        "ix_shipment_return_items_packing_slip_item",
        "shipment_return_items",
        ["packing_slip_item_id"],
    )

    # 5. inventory_locations: new return origin column + relaxed origin CHECK
    op.add_column(
        "inventory_locations",
        sa.Column(
            "shipment_return_item_id",
            sa.Uuid(),
            sa.ForeignKey("shipment_return_items.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_inventory_locations_shipment_return_item",
        "inventory_locations",
        ["shipment_return_item_id"],
    )
    op.drop_constraint("ck_inventory_locations_has_origin", "inventory_locations", type_="check")
    op.create_check_constraint(
        "ck_inventory_locations_has_origin",
        "inventory_locations",
        "(po_line_item_id IS NOT NULL AND receive_line_item_id IS NOT NULL) "
        "OR stock_item_id IS NOT NULL "
        "OR shipment_return_item_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_inventory_locations_has_origin", "inventory_locations", type_="check")
    op.create_check_constraint(
        "ck_inventory_locations_has_origin",
        "inventory_locations",
        "(po_line_item_id IS NOT NULL AND receive_line_item_id IS NOT NULL) OR stock_item_id IS NOT NULL",
    )
    op.drop_index("ix_inventory_locations_shipment_return_item", table_name="inventory_locations")
    op.drop_column("inventory_locations", "shipment_return_item_id")

    op.drop_index("ix_shipment_return_items_packing_slip_item", table_name="shipment_return_items")
    op.drop_index("ix_shipment_return_items_return", table_name="shipment_return_items")
    op.drop_table("shipment_return_items")
    op.drop_index("ix_shipment_returns_packing_slip", table_name="shipment_returns")
    op.drop_table("shipment_returns")

    op.execute("DROP TYPE return_disposition")
    # audit_action 'RETURN' is left in place - Postgres can't drop an enum value without a full
    # rebuild, and a leftover unused value is harmless.
