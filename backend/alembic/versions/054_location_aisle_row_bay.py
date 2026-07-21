"""Reshape warehouse location to 3-tier aisle > row > bay (drop bin), add row to stock_items

Revision ID: 054
Revises: 053
Create Date: 2026-07-20

Issue #293: the location hierarchy becomes aisle > row > bay. The innermost `bin` tier is
dropped everywhere; stock_items gains the `row` column it lacked (inventory_locations and
opening_items already got `row` in 023). Every composite warehouse index is rebuilt on
(warehouse_id, aisle, row, bay). Dev data is disposable - no backfill.
"""

import sqlalchemy as sa

from alembic import op

revision = "054"
down_revision = "053"
branch_labels = None
depends_on = None

_TABLES = ("inventory_locations", "stock_items", "opening_items")


def upgrade() -> None:
    # stock_items lacked a row column; the other two got it in 023.
    op.add_column("stock_items", sa.Column("row", sa.String(20), nullable=True))

    # Drop the innermost bin tier and rebuild each composite warehouse index on aisle > row > bay.
    for table in _TABLES:
        op.drop_index(f"ix_{table}_warehouse", table_name=table)
        op.drop_column(table, "bin")
        op.create_index(
            f"ix_{table}_warehouse",
            table,
            ["warehouse_id", "aisle", "row", "bay"],
        )


def downgrade() -> None:
    for table in _TABLES:
        op.drop_index(f"ix_{table}_warehouse", table_name=table)
        op.add_column(table, sa.Column("bin", sa.String(20), nullable=True))
        op.create_index(
            f"ix_{table}_warehouse",
            table,
            ["warehouse_id", "aisle", "bay", "bin"],
        )
    op.drop_column("stock_items", "row")
