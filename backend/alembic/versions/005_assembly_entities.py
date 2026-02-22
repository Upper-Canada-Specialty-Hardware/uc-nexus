"""assembly entities: opening_items, opening_item_hardware, shop_assembly_requests, shop_assembly_openings, shop_assembly_opening_items

Revision ID: 005
Revises: 004
Create Date: 2026-02-18
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "005"
down_revision = "004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # opening_items table
    op.create_table(
        "opening_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("opening_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("openings.id"), nullable=False),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column("building", sa.String(), nullable=True),
        sa.Column("floor", sa.String(), nullable=True),
        sa.Column("location", sa.String(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("assembly_completed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "state",
            sa.Enum(
                "IN_INVENTORY",
                "SHIP_READY",
                "SHIPPED_OUT",
                name="opening_item_state",
            ),
            nullable=False,
        ),
        sa.Column("shelf", sa.String(), nullable=True),
        sa.Column("column", sa.String(), nullable=True),
        sa.Column("row", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )

    # opening_item_hardware table
    op.create_table(
        "opening_item_hardware",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("opening_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("opening_items.id"), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
    )

    # shop_assembly_requests table
    op.create_table(
        "shop_assembly_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_number", sa.String(50), unique=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "APPROVED",
                "REJECTED",
                name="shop_assembly_request_status",
            ),
            nullable=False,
        ),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("approved_by", sa.String(), nullable=True),
        sa.Column("rejected_by", sa.String(), nullable=True),
        sa.Column("rejection_reason", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("approved_at", sa.DateTime(), nullable=True),
        sa.Column("rejected_at", sa.DateTime(), nullable=True),
    )

    # shop_assembly_openings table
    op.create_table(
        "shop_assembly_openings",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shop_assembly_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shop_assembly_requests.id"),
            nullable=False,
        ),
        sa.Column("opening_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("openings.id"), nullable=False),
        sa.Column(
            "pull_status",
            sa.Enum(
                "NOT_PULLED",
                "PARTIAL",
                "PULLED",
                name="pull_status",
            ),
            nullable=False,
        ),
        sa.Column("assigned_to", sa.String(), nullable=True),
        sa.Column(
            "assembly_status",
            sa.Enum(
                "PENDING",
                "COMPLETED",
                name="assembly_status",
            ),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )

    # shop_assembly_opening_items table
    op.create_table(
        "shop_assembly_opening_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shop_assembly_opening_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shop_assembly_openings.id"),
            nullable=False,
        ),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
    )

    # Add FK constraint on pull_request_items.opening_item_id now that opening_items exists
    op.create_foreign_key(
        "fk_pull_request_items_opening_item_id",
        "pull_request_items",
        "opening_items",
        ["opening_item_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_pull_request_items_opening_item_id", "pull_request_items", type_="foreignkey")
    op.drop_table("shop_assembly_opening_items")
    op.drop_table("shop_assembly_openings")
    op.drop_table("shop_assembly_requests")
    op.drop_table("opening_item_hardware")
    op.drop_table("opening_items")

    op.execute("DROP TYPE IF EXISTS assembly_status")
    op.execute("DROP TYPE IF EXISTS pull_status")
    op.execute("DROP TYPE IF EXISTS shop_assembly_request_status")
    op.execute("DROP TYPE IF EXISTS opening_item_state")
