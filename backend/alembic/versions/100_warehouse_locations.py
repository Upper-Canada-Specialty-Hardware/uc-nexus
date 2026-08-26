"""Create warehouse_locations registry and backfill occupied combos (#632)

Revision ID: 100
Revises: 099
Create Date: 2026-08-26

The defined-locations registry every location write now validates against. Backfill seeds it with
every distinct occupied (warehouse, aisle, row, bay) combo from inventory_locations and stock_items -
normalized to canonical form (uppercase, trimmed, collapsed whitespace) the way new registrations
are - so nothing currently on a shelf becomes unwritable the moment the gate turns on. Occupied
mirrors the utilization view: inventory rows with quantity > 0, stock rows with
quantity + deficient_quantity > 0. Downgrade drops the table; the strings live on in the item rows.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision = "100"
down_revision = "099"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "warehouse_locations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("warehouse_id", sa.Uuid(), nullable=False),
        sa.Column("aisle", sa.String(length=20), nullable=False),
        sa.Column("row", sa.String(length=20), nullable=False),
        sa.Column("bay", sa.String(length=20), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["warehouse_id"], ["warehouses.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("warehouse_id", "aisle", "row", "bay", name="uq_warehouse_locations_triple"),
    )
    op.create_index("ix_warehouse_locations_warehouse", "warehouse_locations", ["warehouse_id"])

    # Backfill in Python rather than one INSERT..SELECT: normalization is regexp work either way, and
    # two combos that collide only after normalization ("a 1" and "A 1") must become ONE row, which
    # a plain UNION of normalized selects plus the unique constraint would refuse mid-migration.
    conn = op.get_bind()
    occupied = conn.execute(
        sa.text(
            'SELECT DISTINCT warehouse_id, aisle, "row", bay FROM inventory_locations '
            'WHERE warehouse_id IS NOT NULL AND aisle IS NOT NULL AND "row" IS NOT NULL '
            "AND bay IS NOT NULL AND quantity > 0 "
            "UNION "
            'SELECT DISTINCT warehouse_id, aisle, "row", bay FROM stock_items '
            'WHERE warehouse_id IS NOT NULL AND aisle IS NOT NULL AND "row" IS NOT NULL '
            "AND bay IS NOT NULL AND quantity + deficient_quantity > 0"
        )
    ).all()

    def _norm(value: str) -> str:
        return " ".join(value.upper().strip().split())

    now = datetime.utcnow()
    seen: set[tuple] = set()
    rows = []
    for warehouse_id, aisle, row, bay in occupied:
        key = (warehouse_id, _norm(aisle), _norm(row), _norm(bay))
        if key in seen or not all(key[1:]):
            continue
        seen.add(key)
        rows.append(
            {
                "id": uuid.uuid4(),
                "warehouse_id": key[0],
                "aisle": key[1],
                "row": key[2],
                "bay": key[3],
                "active": True,
                "created_at": now,
            }
        )
    if rows:
        op.bulk_insert(
            sa.table(
                "warehouse_locations",
                sa.column("id", sa.Uuid()),
                sa.column("warehouse_id", sa.Uuid()),
                sa.column("aisle", sa.String()),
                sa.column("row", sa.String()),
                sa.column("bay", sa.String()),
                sa.column("active", sa.Boolean()),
                sa.column("created_at", sa.DateTime()),
            ),
            rows,
        )


def downgrade() -> None:
    op.drop_index("ix_warehouse_locations_warehouse", table_name="warehouse_locations")
    op.drop_table("warehouse_locations")
