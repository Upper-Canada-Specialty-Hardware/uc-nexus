"""Add shipping_methods to po_document_settings (issue #230 follow-up)

The generate dialog's Shipping Method is now a dropdown fed by an admin-configurable list, so the
boilerplate row gains a shipping_methods JSON column. The column is NOT NULL; the already-seeded row
is backfilled with the default option set before the constraint is applied.

Revision ID: 050
Revises: 049
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "050"
down_revision = "049"
branch_labels = None
depends_on = None

_DEFAULT = '["LOCAL DELIVERY", "Supply by your freight company", "Supply by our freight company", "Pick up"]'


def upgrade() -> None:
    op.add_column("po_document_settings", sa.Column("shipping_methods", sa.JSON(), nullable=True))
    op.execute(f"UPDATE po_document_settings SET shipping_methods = '{_DEFAULT}' WHERE shipping_methods IS NULL")
    op.alter_column("po_document_settings", "shipping_methods", nullable=False)


def downgrade() -> None:
    op.drop_column("po_document_settings", "shipping_methods")
