"""rename vendor_alias to order_as on po_line_items

Revision ID: 018
Revises: 017
Create Date: 2026-03-26
"""

from alembic import op

revision = "018"
down_revision = "017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("po_line_items", "vendor_alias", new_column_name="order_as")


def downgrade() -> None:
    op.alter_column("po_line_items", "order_as", new_column_name="vendor_alias")
