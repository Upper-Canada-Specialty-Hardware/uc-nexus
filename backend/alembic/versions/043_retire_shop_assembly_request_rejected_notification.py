"""Retire the SHOP_ASSEMBLY_REQUEST_REJECTED notification type (#223)

The SAR approval/reject flow was removed, so the notification it produced no longer
exists. Postgres cannot DROP a value from an enum in place, so recreate notification_type
without it. Any leftover rows of the retired type are deleted first so the column recast
succeeds.

Revision ID: 043
Revises: 042
Create Date: 2026-07-09
"""

from alembic import op

revision = "043"
down_revision = "042"
branch_labels = None
depends_on = None

_WITHOUT = "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED'"
_WITH = "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHOP_ASSEMBLY_REQUEST_REJECTED', 'SHIPMENT_COMPLETED'"


def _recreate(values: str) -> None:
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({values})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")


def upgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type = 'SHOP_ASSEMBLY_REQUEST_REJECTED'")
    _recreate(_WITHOUT)


def downgrade() -> None:
    _recreate(_WITH)
