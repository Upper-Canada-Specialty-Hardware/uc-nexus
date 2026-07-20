"""shipping_out_requests + shipping_out_request_items (accept gate, #293 workstream B)

Adds the two-entity "accept" gate for the shipping-out path: Start-a-Task mints a
ShippingOutRequest (PENDING); a signed-in user accepts it, which mints the existing warehouse
PullRequest (SHIPPING_OUT, PENDING) and stamps pull_request_id. Mirrors the shop-assembly path,
which reuses the pre-existing ShopAssemblyRequest tables.

The item_type column reuses the pull_request_item_type enum already created in migration 004
(create_type=False); only shipping_out_request_status is new here.

Revision ID: 055
Revises: 054
Create Date: 2026-07-20
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "055"
down_revision = "054"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipping_out_requests",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_number", sa.String(50), unique=True, nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "PENDING",
                "APPROVED",
                "REJECTED",
                name="shipping_out_request_status",
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
        sa.Column(
            "pull_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("pull_requests.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_shipping_out_requests_project_status",
        "shipping_out_requests",
        ["project_id", "status"],
    )

    op.create_table(
        "shipping_out_request_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "shipping_out_request_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("shipping_out_requests.id"),
            nullable=False,
        ),
        sa.Column(
            "item_type",
            postgresql.ENUM(
                "LOOSE",
                "OPENING_ITEM",
                name="pull_request_item_type",
                create_type=False,
            ),
            nullable=False,
        ),
        sa.Column("opening_number", sa.String(), nullable=False),
        sa.Column(
            "opening_item_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("opening_items.id"),
            nullable=True,
        ),
        sa.Column("hardware_category", sa.String(), nullable=True),
        sa.Column("product_code", sa.String(), nullable=True),
        sa.Column("requested_quantity", sa.Integer(), nullable=False),
        sa.CheckConstraint(
            "requested_quantity >= 1",
            name="ck_shipping_out_request_items_requested_quantity_positive",
        ),
    )
    op.create_index(
        "ix_shipping_out_request_items_request",
        "shipping_out_request_items",
        ["shipping_out_request_id"],
    )
    op.create_index(
        "ix_shipping_out_request_items_opening_item",
        "shipping_out_request_items",
        ["opening_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_shipping_out_request_items_opening_item", table_name="shipping_out_request_items")
    op.drop_index("ix_shipping_out_request_items_request", table_name="shipping_out_request_items")
    op.drop_table("shipping_out_request_items")

    op.drop_index("ix_shipping_out_requests_project_status", table_name="shipping_out_requests")
    op.drop_table("shipping_out_requests")

    # pull_request_item_type is shared (created in 004) - leave it. Only drop the type this migration made.
    op.execute("DROP TYPE IF EXISTS shipping_out_request_status")
