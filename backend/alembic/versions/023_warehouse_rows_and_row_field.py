"""Add warehouse_rows table, row_id to bins, row to inventory/opening, orientation to aisles

Revision ID: 023
Revises: 022
Create Date: 2026-04-03
"""

import sqlalchemy as sa

from alembic import op

revision = "023"
down_revision = "022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Truncate existing layout data (dev-only, no real data)
    op.execute("DELETE FROM warehouse_bins")
    op.execute("DELETE FROM warehouse_bays")
    op.execute("DELETE FROM warehouse_aisles")

    # Add orientation to aisles
    op.add_column(
        "warehouse_aisles",
        sa.Column("orientation", sa.String(10), nullable=False, server_default="VERTICAL"),
    )

    # Create warehouse_rows table
    op.create_table(
        "warehouse_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aisle_id", sa.Uuid(), sa.ForeignKey("warehouse_aisles.id"), nullable=False),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("aisle_id", "name", name="uq_warehouse_rows_aisle_name"),
    )
    op.create_index("ix_warehouse_rows_aisle", "warehouse_rows", ["aisle_id"])

    # Add row_id FK to warehouse_bins
    op.add_column(
        "warehouse_bins",
        sa.Column("row_id", sa.Uuid(), sa.ForeignKey("warehouse_rows.id"), nullable=True),
    )

    # Add row column to inventory_locations and opening_items
    op.add_column("inventory_locations", sa.Column("row", sa.String(20), nullable=True))
    op.add_column("opening_items", sa.Column("row", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("opening_items", "row")
    op.drop_column("inventory_locations", "row")
    op.drop_column("warehouse_bins", "row_id")
    op.drop_index("ix_warehouse_rows_aisle", table_name="warehouse_rows")
    op.drop_table("warehouse_rows")
    op.drop_column("warehouse_aisles", "orientation")
