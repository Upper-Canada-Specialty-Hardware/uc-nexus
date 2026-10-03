"""shop assembly rejections tell the shop (issue #1242)

- SHOP_ASSEMBLY_REQUEST_REJECTED, a new notification_type value for the shop assembly audience,
  raised when a request is turned down, with the reason.

Downgrade mirrors 126: delete rows of the retiring type first, then recreate notification_type
without it.

Revision ID: 131
Revises: 127
Create Date: 2026-10-03
"""

from alembic import op

revision = "131"
down_revision = "127"
branch_labels = None
depends_on = None

# notification_type as it stands after 126.
_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'GP_WRITE_FAILED', 'RECEIVE_DRAFT_SUBMITTED', 'RECEIVE_DRAFT_REJECTED', "
    "'SHIPPING_REQUEST_REJECTED', 'CLASSIFICATION_CHANGED'"
)


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'SHOP_ASSEMBLY_REQUEST_REJECTED'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type::text = 'SHOP_ASSEMBLY_REQUEST_REJECTED'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
