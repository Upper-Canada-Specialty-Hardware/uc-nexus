"""one primary warehouse per company (issue #1431)

The primary flag decides where a receipt, pull or movement with no warehouse lands, read per company.
Making a building primary read the old primary unlocked and unflagged it, so two admins doing it at
once left two primaries, and the pick between them fell to sort order. The repository now serializes
the change; this partial unique index holds the same rule in the database.

Upgrade first demotes any extra primaries a company already has, keeping the one
`get_primary_warehouse_id` picks today (active first, then oldest, then lowest id), so nothing that
currently routes to a building moves. Downgrade drops the index; the demotions are not restored.

Revision ID: 140
Revises: 139
Create Date: 2026-10-04
"""

from alembic import op

revision = "140"
down_revision = "139"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE warehouses SET is_primary = false
        WHERE is_primary
          AND id NOT IN (
            SELECT DISTINCT ON (company) id
            FROM warehouses
            WHERE is_primary
            ORDER BY company, is_active DESC, created_at, id
          )
        """
    )
    op.execute("CREATE UNIQUE INDEX uq_warehouses_company_primary ON warehouses (company) WHERE is_primary")


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_warehouses_company_primary")
