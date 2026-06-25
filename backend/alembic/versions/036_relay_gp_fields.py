"""Relay/GP integration fields: vendors.gp_vendor_id, purchase_orders.cost_code +
gp_sync_status (uc nexus <-> relay full spec, schema + api changes)

Revision ID: 036
Revises: 035
Create Date: 2026-06-25
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "036"
down_revision = "035"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # GP VENDORID populated by the vendor sync (PM00200 -> Vendor.gp_vendor_id).
    op.add_column("vendors", sa.Column("gp_vendor_id", sa.String(length=15), nullable=True))

    # Per-PO GP cost code (issue #121 dropdown), applied to job-cost lines at GP push time.
    op.add_column("purchase_orders", sa.Column("cost_code", sa.String(length=50), nullable=True))

    # Whether this PO's GP job-cost PO has been created via the relay. NOT NULL with a server default so
    # existing rows backfill to NOT_PUSHED.
    gp_sync_status = postgresql.ENUM("NOT_PUSHED", "SYNCED", "FAILED", name="gp_sync_status")
    gp_sync_status.create(op.get_bind(), checkfirst=True)
    op.add_column(
        "purchase_orders",
        sa.Column(
            "gp_sync_status",
            postgresql.ENUM("NOT_PUSHED", "SYNCED", "FAILED", name="gp_sync_status", create_type=False),
            nullable=False,
            server_default="NOT_PUSHED",
        ),
    )


def downgrade() -> None:
    op.drop_column("purchase_orders", "gp_sync_status")
    op.drop_column("purchase_orders", "cost_code")
    op.drop_column("vendors", "gp_vendor_id")
    op.execute("DROP TYPE gp_sync_status")
