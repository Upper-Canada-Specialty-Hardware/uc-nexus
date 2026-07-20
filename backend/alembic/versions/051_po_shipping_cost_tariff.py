"""PO shipping_cost + tariff_amount (issue #156)

Optional order-time dollar costs captured in the Create/Register PO dialog and editable on the PO
afterward. Nullable on purchase_orders (null = not entered, 0 = entered as zero). po_document_data
gains a tariff_amount totals line (NOT NULL default 0, like freight/misc/tax) that prefills from the
PO value in the generate dialog.

Revision ID: 051
Revises: 050
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

revision = "051"
down_revision = "050"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("shipping_cost", sa.Numeric(12, 2), nullable=True))
    op.add_column("purchase_orders", sa.Column("tariff_amount", sa.Numeric(12, 2), nullable=True))
    op.add_column("po_document_data", sa.Column("tariff_amount", sa.Numeric(12, 2), nullable=True))
    op.execute("UPDATE po_document_data SET tariff_amount = 0 WHERE tariff_amount IS NULL")
    op.alter_column("po_document_data", "tariff_amount", nullable=False)


def downgrade() -> None:
    op.drop_column("po_document_data", "tariff_amount")
    op.drop_column("purchase_orders", "tariff_amount")
    op.drop_column("purchase_orders", "shipping_cost")
