"""no-project pool rows and POs carry a kind: stock or overhead (issue #832)

Overhead is not a new system - it is a flag on rows of the same no-project pool (stock_items). The
flag is chosen once per PO, so purchase_orders gets the same column and receive copies it onto the
pool rows it creates. Every existing pool row and every existing PO is STOCK: the server default
backfills both as the columns are added.

POOL_KIND_CHANGE is the audit action for re-flagging units of a pool row from one kind to the other.

Downgrade: the overhead half cannot be expressed without the column, so overhead rows are merged
back into the stock row of the same shelf where one exists (quantities, deficient quantities, and
any inventory_locations / deficiency_reviews / shipment_return_items that point at them are
moved over), and the audit rows
of the new action are dropped before the enum is recast.

Revision ID: 121
Revises: 120
Create Date: 2026-09-29
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "121"
down_revision = "120"
branch_labels = None
depends_on = None

_KINDS = ("STOCK", "OVERHEAD")

_AUDIT_ACTION_WITHOUT = (
    "'ADJUSTMENT', 'MOVE', 'UNLOCATE', 'RECEIVE', 'PULL_DEDUCTION', 'SPOT_CHECK', 'PUT_AWAY', "
    "'DESTOCK', 'ALLOCATE_FROM_STOCK', 'RECLASSIFY', 'REPORT_DEFICIENT', 'RESOLVE_DEFICIENT', "
    "'TRANSFER', 'RETURN', 'INSTALL_PROGRESS', 'ASSEMBLY_COMPLETE', 'REPLACEMENT_RECEIVED', "
    "'REPLACEMENT_INSTALL', 'PULL_STAGED', 'PULL_RESTOCK', 'PULL_CANCELLED'"
)

# The shelf identity a pool row merges on, minus the kind. NULL-safe, since unlocated rows are real.
_SAME_SHELF = """
    s.warehouse_id = o.warehouse_id
    AND s.hardware_category = o.hardware_category
    AND s.product_code = o.product_code
    AND s.aisle IS NOT DISTINCT FROM o.aisle
    AND s.row IS NOT DISTINCT FROM o.row
    AND s.bay IS NOT DISTINCT FROM o.bay
"""


def upgrade() -> None:
    postgresql.ENUM(*_KINDS, name="pool_kind").create(op.get_bind(), checkfirst=True)
    kind = postgresql.ENUM(*_KINDS, name="pool_kind", create_type=False)
    op.add_column("stock_items", sa.Column("kind", kind, nullable=False, server_default="STOCK"))
    op.add_column("purchase_orders", sa.Column("pool_kind", kind, nullable=False, server_default="STOCK"))
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'POOL_KIND_CHANGE'")


def downgrade() -> None:
    op.execute("DELETE FROM inventory_audit_log WHERE action = 'POOL_KIND_CHANGE'")
    op.execute("ALTER TYPE audit_action RENAME TO audit_action_old")
    op.execute(f"CREATE TYPE audit_action AS ENUM ({_AUDIT_ACTION_WITHOUT})")
    op.execute("ALTER TABLE inventory_audit_log ALTER COLUMN action TYPE audit_action USING action::text::audit_action")
    op.execute("DROP TYPE audit_action_old")

    # Fold each overhead row into the stock row of the same shelf, when there is one, so the
    # pre-#832 schema does not end up holding two rows for one merge key. An overhead row with no
    # stock twin simply becomes a stock row when the column goes.
    pairs = f"""
        SELECT o.id AS overhead_id, s.id AS stock_id
        FROM stock_items o
        JOIN stock_items s ON s.kind = 'STOCK' AND {_SAME_SHELF}
        WHERE o.kind = 'OVERHEAD'
    """
    op.execute(
        f"""
        UPDATE stock_items s
        SET quantity = s.quantity + agg.quantity,
            deficient_quantity = s.deficient_quantity + agg.deficient_quantity,
            unit_cost = COALESCE(s.unit_cost, agg.unit_cost)
        FROM (
            SELECT p.stock_id,
                   SUM(o.quantity) AS quantity,
                   SUM(o.deficient_quantity) AS deficient_quantity,
                   MAX(o.unit_cost) AS unit_cost
            FROM ({pairs}) p JOIN stock_items o ON o.id = p.overhead_id
            GROUP BY p.stock_id
        ) agg
        WHERE s.id = agg.stock_id
        """
    )
    op.execute(
        f"""
        UPDATE inventory_locations il SET stock_item_id = p.stock_id
        FROM ({pairs}) p WHERE il.stock_item_id = p.overhead_id
        """
    )
    op.execute(
        f"""
        UPDATE deficiency_reviews d SET stock_item_id = p.stock_id
        FROM ({pairs}) p WHERE d.stock_item_id = p.overhead_id
        """
    )
    op.execute(
        f"""
        UPDATE deficiency_reviews d SET resulting_stock_item_id = p.stock_id
        FROM ({pairs}) p WHERE d.resulting_stock_item_id = p.overhead_id
        """
    )
    op.execute(
        f"""
        UPDATE shipment_return_items r SET resulting_stock_item_id = p.stock_id
        FROM ({pairs}) p WHERE r.resulting_stock_item_id = p.overhead_id
        """
    )
    op.execute(f"DELETE FROM stock_items o USING ({pairs}) p WHERE o.id = p.overhead_id")

    op.drop_column("purchase_orders", "pool_kind")
    op.drop_column("stock_items", "kind")
    op.execute("DROP TYPE IF EXISTS pool_kind")
