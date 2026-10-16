"""inventory rows with no PO line and no return say how they came in (issue #1699)

A project inventory row whose only origin is a stock_items row could have come from an allocate off the
pool, the legacy inventory migration, or a cancelled pull's restock, and nothing on it says which: stock
rows merge units of every source, and a transfer or split copies the origin onto a new row. The new
`entry_source` column records it when the row is made, and travels with the other origin fields.

Backfill, for the stock-origin rows already there (PO-origin and return-origin rows stay null):
  - LEGACY_MIGRATION where a no-PO migration mark names the row's project, category and product
  - PULL_RESTOCK where the row's own audit history opens with a pull restock rather than an allocate
  - STOCK_ALLOCATION otherwise

Downgrade drops the column and its type.

Revision ID: 144
Revises: 143
Create Date: 2026-10-16
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "144"
down_revision = "143"
branch_labels = None
depends_on = None

_SOURCES = ("STOCK_ALLOCATION", "LEGACY_MIGRATION", "PULL_RESTOCK")

_STOCK_ORIGIN = """
    il.po_line_item_id IS NULL
    AND il.shipment_return_item_id IS NULL
    AND il.stock_item_id IS NOT NULL
"""


def upgrade() -> None:
    postgresql.ENUM(*_SOURCES, name="inventory_entry_source").create(op.get_bind(), checkfirst=True)
    source = postgresql.ENUM(*_SOURCES, name="inventory_entry_source", create_type=False)
    op.add_column("inventory_locations", sa.Column("entry_source", source, nullable=True))

    op.execute(
        f"""
        UPDATE inventory_locations il SET entry_source = 'LEGACY_MIGRATION'
        WHERE {_STOCK_ORIGIN}
          AND EXISTS (
            SELECT 1 FROM sharepoint_migration_marks m
            WHERE m.project_id = il.project_id
              AND m.hardware_category = il.hardware_category
              AND m.product_code = il.product_code
              AND m.po_line_item_id IS NULL
          )
        """
    )
    # The row's first audit event is what made it: a restock that had no row to land on creates one,
    # where an allocate is recorded against the pool row and never against the new project row.
    op.execute(
        f"""
        UPDATE inventory_locations il SET entry_source = 'PULL_RESTOCK'
        WHERE {_STOCK_ORIGIN}
          AND il.entry_source IS NULL
          AND (
            SELECT a.action FROM inventory_audit_log a
            WHERE a.entity_id = il.id
            ORDER BY a.created_at
            LIMIT 1
          ) = 'PULL_RESTOCK'
        """
    )
    op.execute(
        f"""
        UPDATE inventory_locations il SET entry_source = 'STOCK_ALLOCATION'
        WHERE {_STOCK_ORIGIN} AND il.entry_source IS NULL
        """
    )


def downgrade() -> None:
    op.drop_column("inventory_locations", "entry_source")
    postgresql.ENUM(name="inventory_entry_source").drop(op.get_bind(), checkfirst=True)
