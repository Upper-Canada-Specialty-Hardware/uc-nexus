"""Drop warehouse layout tables and normalize aisle/bay/bin values across tables.

Revision ID: 031
Revises: 030
Create Date: 2026-06-09

The warehouse map feature is removed (decided out of band). The four physical-layout tables
(warehouse_aisles, warehouse_rows, warehouse_bays, warehouse_bins) no longer have a UI and
are dropped here. As a follow-on, every aisle/bay/bin string across inventory_locations,
opening_items, and stock_items is normalized to upper-case + trimmed + collapsed-whitespace
so the locations tab no longer treats "A-22-L" and "a-22-l" as distinct bins.
"""

import sqlalchemy as sa

from alembic import op

revision = "031"
down_revision = "030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Drop the four physical-layout tables. Children first to satisfy FK dependencies.
    op.drop_table("warehouse_bins")
    op.drop_table("warehouse_bays")
    op.drop_table("warehouse_rows")
    op.drop_table("warehouse_aisles")

    # Normalize existing location strings in place. SQL expression mirrors the python helper:
    # uppercase, trim, collapse internal whitespace via regexp_replace.
    normalize_sql = "regexp_replace(btrim(upper({col})), '[[:space:]]+', ' ', 'g')"
    for table in ("inventory_locations", "opening_items", "stock_items"):
        for col in ("aisle", "bay", "bin"):
            op.execute(f"UPDATE {table} SET {col} = {normalize_sql.format(col=col)} WHERE {col} IS NOT NULL")


def downgrade() -> None:
    # Recreate the four tables as they existed before drop. Schema matches migration 022 and 023.
    op.create_table(
        "warehouse_aisles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(length=20), nullable=False, unique=True),
        sa.Column("label", sa.String(length=80), nullable=True),
        sa.Column("orientation", sa.String(length=16), nullable=False),
        sa.Column("x_position", sa.Integer(), nullable=False),
        sa.Column("y_position", sa.Integer(), nullable=False),
        sa.Column("width", sa.Integer(), nullable=False),
        sa.Column("height", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "warehouse_rows",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aisle_id", sa.Uuid(), sa.ForeignKey("warehouse_aisles.id"), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("aisle_id", "name", name="uq_warehouse_rows_aisle_name"),
    )
    op.create_index("ix_warehouse_rows_aisle", "warehouse_rows", ["aisle_id"])

    op.create_table(
        "warehouse_bays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aisle_id", sa.Uuid(), sa.ForeignKey("warehouse_aisles.id"), nullable=False),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("row_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("col_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("aisle_id", "name", name="uq_warehouse_bays_aisle_name"),
    )
    op.create_index("ix_warehouse_bays_aisle", "warehouse_bays", ["aisle_id"])

    op.create_table(
        "warehouse_bins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bay_id", sa.Uuid(), sa.ForeignKey("warehouse_bays.id"), nullable=False),
        sa.Column("row_id", sa.Uuid(), sa.ForeignKey("warehouse_rows.id"), nullable=True),
        sa.Column("name", sa.String(length=20), nullable=False),
        sa.Column("row_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("col_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("bay_id", "name", name="uq_warehouse_bins_bay_name"),
    )
    op.create_index("ix_warehouse_bins_bay", "warehouse_bins", ["bay_id"])

    # Note: downgrade does NOT un-normalize location strings — original casing is lost.
