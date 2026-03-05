"""rename location fields shelf/column/row to aisle/bay/bin

Revision ID: 012
Revises: 011
Create Date: 2026-03-05
"""

from alembic import op

# revision identifiers, used by Alembic.
revision = "012"
down_revision = "011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # inventory_locations table
    op.alter_column("inventory_locations", "shelf", new_column_name="aisle")
    op.alter_column("inventory_locations", "column", new_column_name="bay")
    op.alter_column("inventory_locations", "row", new_column_name="bin")
    op.execute("ALTER INDEX ix_inventory_locations_shelf RENAME TO ix_inventory_locations_aisle")

    # opening_items table
    op.alter_column("opening_items", "shelf", new_column_name="aisle")
    op.alter_column("opening_items", "column", new_column_name="bay")
    op.alter_column("opening_items", "row", new_column_name="bin")


def downgrade() -> None:
    # opening_items table
    op.alter_column("opening_items", "bin", new_column_name="row")
    op.alter_column("opening_items", "bay", new_column_name="column")
    op.alter_column("opening_items", "aisle", new_column_name="shelf")

    # inventory_locations table
    op.execute("ALTER INDEX ix_inventory_locations_aisle RENAME TO ix_inventory_locations_shelf")
    op.alter_column("inventory_locations", "bin", new_column_name="row")
    op.alter_column("inventory_locations", "bay", new_column_name="column")
    op.alter_column("inventory_locations", "aisle", new_column_name="shelf")
