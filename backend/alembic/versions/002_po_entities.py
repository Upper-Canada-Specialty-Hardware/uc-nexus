"""PO entities: purchase_orders, po_line_items + FK on hardware_items

Revision ID: 002
Revises: 001
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "002"
down_revision = "001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "purchase_orders",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("po_number", sa.String(50), unique=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "DRAFT",
                "ORDERED",
                "PARTIALLY_RECEIVED",
                "CLOSED",
                "CANCELLED",
                name="po_status",
            ),
            nullable=False,
        ),
        sa.Column("vendor_name", sa.String(), nullable=True),
        sa.Column("vendor_contact", sa.String(), nullable=True),
        sa.Column("expected_delivery_date", sa.Date(), nullable=True),
        sa.Column("ordered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "po_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column(
            "classification",
            sa.Enum(
                "SITE_HARDWARE",
                "SHOP_HARDWARE",
                name="classification",
            ),
            nullable=False,
        ),
        sa.Column("ordered_quantity", sa.Integer(), nullable=False),
        sa.Column("received_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("unit_cost", sa.Numeric(10, 4), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    op.create_foreign_key(
        "fk_hardware_items_po_line_item_id",
        "hardware_items",
        "po_line_items",
        ["po_line_item_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_hardware_items_po_line_item_id", "hardware_items", type_="foreignkey")
    op.drop_table("po_line_items")
    op.drop_table("purchase_orders")
    op.execute("DROP TYPE IF EXISTS po_status")
