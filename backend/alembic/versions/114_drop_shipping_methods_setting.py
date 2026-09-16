"""Drop shipping_methods from po_document_settings (issue #703)

The Generate PO Document dialog's Shipping method is plain free text now, so nothing reads the
admin-configured option list any more and the column goes. The downgrade puts it back exactly as
migration 050 created it: added nullable, backfilled with the default option set, then made NOT NULL.

Revision ID: 114
Revises: 113
Create Date: 2026-09-16
"""

import sqlalchemy as sa

from alembic import op

revision = "114"
down_revision = "113"
branch_labels = None
depends_on = None

_DEFAULT = '["LOCAL DELIVERY", "Supply by your freight company", "Supply by our freight company", "Pick up"]'


def upgrade() -> None:
    op.drop_column("po_document_settings", "shipping_methods")


def downgrade() -> None:
    op.add_column("po_document_settings", sa.Column("shipping_methods", sa.JSON(), nullable=True))
    op.execute(f"UPDATE po_document_settings SET shipping_methods = '{_DEFAULT}' WHERE shipping_methods IS NULL")
    op.alter_column("po_document_settings", "shipping_methods", nullable=False)
