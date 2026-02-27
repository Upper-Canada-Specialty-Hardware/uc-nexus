"""make po_line_item classification nullable

Revision ID: 011
Revises: 010
Create Date: 2026-02-27
"""

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision = "011"
down_revision = "010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "po_line_items",
        "classification",
        existing_type=sa.Enum("SITE_HARDWARE", "SHOP_HARDWARE", name="classification", create_constraint=True),
        nullable=True,
    )


def downgrade() -> None:
    # Backfill NULLs before re-applying NOT NULL
    op.execute("UPDATE po_line_items SET classification = 'SITE_HARDWARE' WHERE classification IS NULL")
    op.alter_column(
        "po_line_items",
        "classification",
        existing_type=sa.Enum("SITE_HARDWARE", "SHOP_HARDWARE", name="classification", create_constraint=True),
        nullable=False,
    )
