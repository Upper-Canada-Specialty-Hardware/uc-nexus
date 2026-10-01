"""a fully returned scheduled shipment is cancelled (issue #973)

Adds CANCELLED to shipment_status. A SCHEDULED shipment whose every returnable line has been returned
never left, so it becomes CANCELLED: no edit, no pick-up, no Delivery Request. Shipments already fully
returned while scheduled are backfilled.

Downgrade puts cancelled shipments back to SCHEDULED (what they read as before) and recreates the
enum without the value.

Revision ID: 124
Revises: 123
Create Date: 2026-10-01
"""

from alembic import op

revision = "124"
down_revision = "123"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ADD VALUE commits on its own so the backfill below can use the new label.
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE shipment_status ADD VALUE IF NOT EXISTS 'CANCELLED'")
    op.execute(
        """
        UPDATE packing_slips ps SET status = 'CANCELLED'
        WHERE ps.status = 'SCHEDULED'
          AND EXISTS (SELECT 1 FROM packing_slip_items i WHERE i.packing_slip_id = ps.id AND NOT i.is_manual)
          AND NOT EXISTS (
            SELECT 1 FROM packing_slip_items i
            WHERE i.packing_slip_id = ps.id AND NOT i.is_manual
              AND i.quantity > COALESCE((
                SELECT SUM(ri.quantity) FROM shipment_return_items ri
                JOIN shipment_returns r ON r.id = ri.shipment_return_id
                WHERE r.packing_slip_id = ps.id AND ri.packing_slip_item_id = i.id
              ), 0)
          )
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE packing_slips ALTER COLUMN status DROP DEFAULT")
    op.execute("UPDATE packing_slips SET status = 'SCHEDULED' WHERE status::text = 'CANCELLED'")
    op.execute("ALTER TYPE shipment_status RENAME TO shipment_status_old")
    op.execute("CREATE TYPE shipment_status AS ENUM ('SCHEDULED', 'PICKED_UP', 'DELIVERED')")
    op.execute("ALTER TABLE packing_slips ALTER COLUMN status TYPE shipment_status USING status::text::shipment_status")
    op.execute("DROP TYPE shipment_status_old")
    op.execute("ALTER TABLE packing_slips ALTER COLUMN status SET DEFAULT 'DELIVERED'")  # 077's default
