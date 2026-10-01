"""left-behind pool rows carry a real $0, not an empty cost (issue #957)

A destock or deficiency resolution with "left behind - $0 cost" stored an empty unit cost, which the
stock pool prints as "—", the mark for a cost nobody knows. Left behind is $0 on purpose (#942), so
from now on it stores 0. This backfills the rows those moves already made: every pool row an audit
event names as the landing row of a ZERO destock whose cost is still empty.

Downgrade is a no-op: an empty cost and $0 value the same, and the rows cannot be told apart from
ones that were $0 already.

Revision ID: 122
Revises: 121
Create Date: 2026-10-01
"""

from alembic import op

revision = "122"
down_revision = "121"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE stock_items SET unit_cost = 0
        WHERE unit_cost IS NULL
          AND id IN (
            SELECT (detail ->> 'stockItemId')::uuid FROM inventory_audit_log
            WHERE detail ->> 'destockCost' = 'ZERO' AND detail ->> 'stockItemId' IS NOT NULL
            UNION
            SELECT (detail ->> 'resultingStockItemId')::uuid FROM inventory_audit_log
            WHERE detail ->> 'destockCost' = 'ZERO' AND detail ->> 'resultingStockItemId' IS NOT NULL
          )
        """
    )


def downgrade() -> None:
    pass
