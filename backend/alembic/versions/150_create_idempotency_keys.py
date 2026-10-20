"""create keys on shipping-out requests and shipment returns, so a resend writes nothing new (issue #1552)

Warehouse wifi drops after the server commits but before the reply lands, and the user confirms again.
Both creates now take a key the browser minted when the dialog opened; a create that finds its key
already written returns that row. Unique, and nullable: rows written before this have none.

Downgrade drops the indexes and the columns.

Revision ID: 150
Revises: 149
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "150"
down_revision = "149"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("shipping_out_requests", sa.Column("create_idempotency_key", sa.String(length=100), nullable=True))
    op.create_index(
        "ix_shipping_out_requests_create_idempotency_key",
        "shipping_out_requests",
        ["create_idempotency_key"],
        unique=True,
    )
    op.add_column("shipment_returns", sa.Column("create_idempotency_key", sa.String(length=100), nullable=True))
    op.create_index(
        "ix_shipment_returns_create_idempotency_key",
        "shipment_returns",
        ["create_idempotency_key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_shipment_returns_create_idempotency_key", table_name="shipment_returns")
    op.drop_column("shipment_returns", "create_idempotency_key")
    op.drop_index("ix_shipping_out_requests_create_idempotency_key", table_name="shipping_out_requests")
    op.drop_column("shipping_out_requests", "create_idempotency_key")
