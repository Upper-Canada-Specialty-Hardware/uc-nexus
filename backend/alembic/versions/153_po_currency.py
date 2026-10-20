"""a PO's currency, and the currency every carried unit cost is in (issue #1557)

- purchase_orders.currency: GP's CURNCYID for the PO, stamped at registration and kept by the mirror.
- stock_items.cost_currency and inventory_locations.cost_currency: the currency of the row's own
  unit_cost, which travels with the cost between rows.

All three are nullable and null reads as CAD, the functional currency, so every existing row keeps the
value it had. The PO currency is filled in by the PO sync's currency backfill, not here: only GP knows it.

Revision ID: 153
Revises: 152
Create Date: 2026-10-20
"""

import sqlalchemy as sa

from alembic import op

revision = "153"
down_revision = "152"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("currency", sa.String(length=15), nullable=True))
    op.add_column("stock_items", sa.Column("cost_currency", sa.String(length=15), nullable=True))
    op.add_column("inventory_locations", sa.Column("cost_currency", sa.String(length=15), nullable=True))


def downgrade() -> None:
    op.drop_column("inventory_locations", "cost_currency")
    op.drop_column("stock_items", "cost_currency")
    op.drop_column("purchase_orders", "currency")
