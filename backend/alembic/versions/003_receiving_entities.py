"""receiving entities: receive_records, receive_line_items, inventory_locations

Revision ID: 003
Revises: 002
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "003"
down_revision = "002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "receive_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("po_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("purchase_orders.id"), nullable=False),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("received_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "receive_line_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "receive_record_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("receive_records.id"), nullable=False
        ),
        sa.Column("po_line_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("po_line_items.id"), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity_received", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )

    op.create_table(
        "inventory_locations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("po_line_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("po_line_items.id"), nullable=False),
        sa.Column(
            "receive_line_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("receive_line_items.id"),
            nullable=False,
        ),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("shelf", sa.String(20), nullable=True),
        sa.Column("column", sa.String(20), nullable=True),
        sa.Column("row", sa.String(20), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("inventory_locations")
    op.drop_table("receive_line_items")
    op.drop_table("receive_records")
