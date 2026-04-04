"""Add warehouse layout tables (aisles, bays, bins)

Revision ID: 022
Revises: 021
Create Date: 2026-04-03
"""

import sqlalchemy as sa
from sqlalchemy import text

from alembic import op

revision = "022"
down_revision = "021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Aisles
    op.create_table(
        "warehouse_aisles",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(20), nullable=False, unique=True),
        sa.Column("label", sa.String(100), nullable=True),
        sa.Column("x_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("y_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("width", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("height", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_warehouse_aisles_active", "warehouse_aisles", ["is_active"])

    # Bays
    op.create_table(
        "warehouse_bays",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("aisle_id", sa.Uuid(), sa.ForeignKey("warehouse_aisles.id"), nullable=False),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("row_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("col_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("aisle_id", "name", name="uq_warehouse_bays_aisle_name"),
    )
    op.create_index("ix_warehouse_bays_aisle", "warehouse_bays", ["aisle_id"])

    # Bins
    op.create_table(
        "warehouse_bins",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("bay_id", sa.Uuid(), sa.ForeignKey("warehouse_bays.id"), nullable=False),
        sa.Column("name", sa.String(20), nullable=False),
        sa.Column("row_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("col_position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("capacity", sa.Integer(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("bay_id", "name", name="uq_warehouse_bins_bay_name"),
    )
    op.create_index("ix_warehouse_bins_bay", "warehouse_bins", ["bay_id"])

    # Backfill: create warehouse layout records from existing inventory data
    conn = op.get_bind()

    # Get distinct aisles from inventory_locations and opening_items
    aisle_rows = conn.execute(
        text("""
            SELECT DISTINCT aisle FROM (
                SELECT aisle FROM inventory_locations WHERE aisle IS NOT NULL
                UNION
                SELECT aisle FROM opening_items WHERE aisle IS NOT NULL
            ) t ORDER BY aisle
        """)
    ).fetchall()

    for i, (aisle_name,) in enumerate(aisle_rows):
        aisle_id = conn.execute(
            text("""
                INSERT INTO warehouse_aisles (id, name, x_position, y_position, width, height, is_active, created_at, updated_at)
                VALUES (gen_random_uuid(), :name, :x, 0, 1, 1, true, now(), now())
                RETURNING id
            """),
            {"name": aisle_name, "x": i},
        ).scalar()

        # Get distinct bays for this aisle
        bay_rows = conn.execute(
            text("""
                SELECT DISTINCT bay FROM (
                    SELECT bay FROM inventory_locations WHERE aisle = :aisle AND bay IS NOT NULL
                    UNION
                    SELECT bay FROM opening_items WHERE aisle = :aisle AND bay IS NOT NULL
                ) t ORDER BY bay
            """),
            {"aisle": aisle_name},
        ).fetchall()

        for j, (bay_name,) in enumerate(bay_rows):
            bay_id = conn.execute(
                text("""
                    INSERT INTO warehouse_bays (id, aisle_id, name, row_position, col_position, is_active, created_at, updated_at)
                    VALUES (gen_random_uuid(), :aisle_id, :name, :row, 0, true, now(), now())
                    RETURNING id
                """),
                {"aisle_id": aisle_id, "name": bay_name, "row": j},
            ).scalar()

            # Get distinct bins for this aisle+bay
            bin_rows = conn.execute(
                text("""
                    SELECT DISTINCT bin FROM (
                        SELECT bin FROM inventory_locations WHERE aisle = :aisle AND bay = :bay AND bin IS NOT NULL
                        UNION
                        SELECT bin FROM opening_items WHERE aisle = :aisle AND bay = :bay AND bin IS NOT NULL
                    ) t ORDER BY bin
                """),
                {"aisle": aisle_name, "bay": bay_name},
            ).fetchall()

            for k, (bin_name,) in enumerate(bin_rows):
                conn.execute(
                    text("""
                        INSERT INTO warehouse_bins (id, bay_id, name, row_position, col_position, is_active, created_at, updated_at)
                        VALUES (gen_random_uuid(), :bay_id, :name, :row, 0, true, now(), now())
                    """),
                    {"bay_id": bay_id, "name": bin_name, "row": k},
                )


def downgrade() -> None:
    op.drop_index("ix_warehouse_bins_bay", table_name="warehouse_bins")
    op.drop_table("warehouse_bins")
    op.drop_index("ix_warehouse_bays_aisle", table_name="warehouse_bays")
    op.drop_table("warehouse_bays")
    op.drop_index("ix_warehouse_aisles_active", table_name="warehouse_aisles")
    op.drop_table("warehouse_aisles")
