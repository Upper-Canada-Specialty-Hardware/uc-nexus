"""add vendor_alias to po_line_items

Revision ID: 012
Revises: 011
Create Date: 2026-03-05
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("po_line_items", sa.Column("vendor_alias", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("po_line_items", "vendor_alias")
