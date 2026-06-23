"""Add warehouses table and warehouse_id FK on inventory_locations / stock_items / opening_items

Revision ID: 033
Revises: 032
Create Date: 2026-06-23
"""

import sqlalchemy as sa

from alembic import op

revision = "033"
down_revision = "032"
branch_labels = None
depends_on = None

_TABLES = ("inventory_locations", "stock_items", "opening_items")


def upgrade() -> None:
    op.create_table(
        "warehouses",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("code", sa.String(20), nullable=False),
        sa.Column("address", sa.String(), nullable=True),
        sa.Column("city", sa.String(), nullable=True),
        sa.Column("province", sa.String(), nullable=True),
        sa.Column("postal_code", sa.String(), nullable=True),
        sa.Column("is_primary", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_warehouses_name"),
        sa.UniqueConstraint("code", name="uq_warehouses_code"),
    )

    # Seed the two physical warehouses (Warden is primary / default for backfill)
    op.execute(
        """
        INSERT INTO warehouses (id, name, code, is_primary, is_active, created_at, updated_at)
        VALUES
            (gen_random_uuid(), 'Warden', 'WRD', true, true, now(), now()),
            (gen_random_uuid(), 'VP', 'VP', false, true, now(), now())
        """
    )

    for table in _TABLES:
        op.add_column(table, sa.Column("warehouse_id", sa.Uuid(), nullable=True))
        op.create_foreign_key(
            f"fk_{table}_warehouse_id",
            table,
            "warehouses",
            ["warehouse_id"],
            ["id"],
            ondelete="RESTRICT",
        )
        # Backfill every existing row to the primary warehouse
        op.execute(
            f"""
            UPDATE {table}
            SET warehouse_id = (SELECT id FROM warehouses WHERE is_primary = true LIMIT 1)
            WHERE warehouse_id IS NULL
            """
        )
        op.alter_column(table, "warehouse_id", nullable=False)
        op.create_index(
            f"ix_{table}_warehouse",
            table,
            ["warehouse_id", "aisle", "bay", "bin"],
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_warehouse", table_name=table)
        op.drop_constraint(f"fk_{table}_warehouse_id", table, type_="foreignkey")
        op.drop_column(table, "warehouse_id")
    op.drop_table("warehouses")
