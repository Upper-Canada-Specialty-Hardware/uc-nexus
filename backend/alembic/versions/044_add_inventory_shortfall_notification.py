"""Add INVENTORY_SHORTFALL to the notification_type enum (#224)

The two inventory-sufficiency gates (import "Start a Request" and warehouse approve_pull_request)
notify the PO with a "couldn't be fulfilled - backfill needed" signal carrying the shortfall
detail. That signal is a new notification type.

Revision ID: 044
Revises: 043
Create Date: 2026-07-09
"""

from alembic import op

revision = "044"
down_revision = "043"
branch_labels = None
depends_on = None

_WITHOUT = "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED'"


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'INVENTORY_SHORTFALL'")


def downgrade() -> None:
    # Postgres cannot DROP a value from an enum in place, so recreate notification_type without it
    # (mirrors migration 043). Any leftover rows of the retired type are deleted first so the recast
    # succeeds.
    op.execute("DELETE FROM notifications WHERE type = 'INVENTORY_SHORTFALL'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
