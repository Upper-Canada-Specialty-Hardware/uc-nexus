"""Drop the vendor mirror (issue #200): purchase_orders now store the GP vendor id + a name snapshot
directly (picked live from gpVendors at push time), so vendors.gp_vendor_id - the sync'd mirror the
now-removed syncGpVendors mutation used to fill - is no longer needed.

Revision ID: 040
Revises: 039
Create Date: 2026-07-07
"""

import sqlalchemy as sa

from alembic import op

revision = "040"
down_revision = "039"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("gp_vendor_id", sa.String(length=15), nullable=True))
    op.add_column("purchase_orders", sa.Column("vendor_name_snapshot", sa.String(), nullable=True))
    op.drop_column("vendors", "gp_vendor_id")


def downgrade() -> None:
    op.add_column("vendors", sa.Column("gp_vendor_id", sa.String(length=15), nullable=True))
    op.drop_column("purchase_orders", "vendor_name_snapshot")
    op.drop_column("purchase_orders", "gp_vendor_id")
