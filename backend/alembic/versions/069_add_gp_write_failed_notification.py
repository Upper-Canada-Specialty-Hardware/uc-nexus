"""Add GP_WRITE_FAILED to the notification_type enum (#353 PR E)

Revision ID: 069
Revises: 068
Create Date: 2026-07-27

The outbox absorbs an offline relay silently and by design - that is the point of it. The one
outcome that must NOT be silent is a queued write that died for good: GP rejected it, it is ambiguous
(GP may already hold it), the UC Nexus persist refused it after GP committed, or it exhausted its
retries. Without a signal, "queued" and "quietly dead" look identical from the warehouse floor.

Routed to the PO audience for a register-PO write and the warehouse audience for a receive - whoever
would have been standing in front of the failure had it happened online.

Downgrade mirrors migration 044 exactly: delete rows of the retiring type first (an enum recast fails
on a value that is about to stop existing), then recreate notification_type without it.
"""

from alembic import op

revision = "069"
down_revision = "068"
branch_labels = None
depends_on = None

_NEW_TYPE = "GP_WRITE_FAILED"

_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'REPLACEMENT_AFTER_SHIPMENT', 'ASSEMBLY_WORK_AVAILABLE', "
    "'REPLACEMENT_ARRIVED', 'PULL_UNBLOCKED'"
)


def upgrade() -> None:
    op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{_NEW_TYPE}'")


def downgrade() -> None:
    op.execute(f"DELETE FROM notifications WHERE type = '{_NEW_TYPE}'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
