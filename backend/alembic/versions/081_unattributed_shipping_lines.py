"""Let a shipping line carry no opening at all

Revision ID: 081
Revises: 080
Create Date: 2026-08-03

The Shipping module can now raise a request straight off project inventory (#451), for the loose
stock a schedule line never accounted for. Inventory is keyed by project, warehouse, category and
product and carries no opening - that is the point of it (docs/HARDWARE_IDENTITY_LIFECYCLE.md) - so
a line raised from a shelf has no opening to name. Writing one in anyway would be a claim the
schedule never made, and the shipper would have to invent it.

Schedule-driven lines are unaffected: they still carry the opening they came off, which is what the
pick sheet groups its carts by.

The downgrade backfills a visible placeholder before restoring NOT NULL rather than deleting the
rows. An unattributed line is a real request somebody made, and dropping it on a rollback would
silently un-ask for hardware.
"""

import sqlalchemy as sa

from alembic import op

revision = "081"
down_revision = "080"
branch_labels = None
depends_on = None

_TABLES = ("shipping_out_request_items", "pull_request_items")
_PLACEHOLDER = "(unattributed)"


def upgrade() -> None:
    for table in _TABLES:
        op.alter_column(table, "opening_number", existing_type=sa.String(), nullable=True)


def downgrade() -> None:
    for table in _TABLES:
        op.execute(
            sa.text(f"UPDATE {table} SET opening_number = :placeholder WHERE opening_number IS NULL").bindparams(
                placeholder=_PLACEHOLDER
            )
        )
        op.alter_column(table, "opening_number", existing_type=sa.String(), nullable=False)
