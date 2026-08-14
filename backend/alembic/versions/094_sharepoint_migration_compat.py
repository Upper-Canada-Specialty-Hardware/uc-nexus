"""Unit cost on inventory rows + a SharePoint-migration run marker

Revision ID: 094
Revises: 093
Create Date: 2026-08-14

The SharePoint migration brings across hardware that was bought and received years ago in GP under
UBC, which Nexus (pointed at TUBC) cannot see. There is no PO line in Nexus to hang a cost on, so the
cost has to live on the inventory rows themselves:

- `stock_items.unit_cost` and `inventory_locations.unit_cost`, both nullable numeric(10,4). Null on
  every row that has a PO origin (its cost stays on the PO line, read by coalesce); set only where the
  units entered off-PO, which today is the migration. Valuation reads coalesce(po_line.unit_cost,
  row.unit_cost, 0), so a PO row and a migrated row both value correctly.

- `sharepoint_migration_runs` - one row per completed run. `has_any_inventory` was never an
  idempotency marker (it answers "is this database empty", true on any environment that ever received
  a PO); this table lets the wizard's re-run warning become definitive. Not preserved across a reset,
  so a full data reset clears it and the cutover can run the migration again.
"""

import sqlalchemy as sa

from alembic import op

revision = "094"
down_revision = "093"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("stock_items", sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True))
    op.add_column("inventory_locations", sa.Column("unit_cost", sa.Numeric(10, 4), nullable=True))

    op.create_table(
        "sharepoint_migration_runs",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("run_at", sa.DateTime(), nullable=False),
        sa.Column("performed_by", sa.String(), nullable=False),
        sa.Column("entry_count", sa.Integer(), nullable=False),
        sa.Column("unit_count", sa.Integer(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    op.drop_table("sharepoint_migration_runs")
    op.drop_column("inventory_locations", "unit_cost")
    op.drop_column("stock_items", "unit_cost")
