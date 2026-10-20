"""the warehouse is told when a pull is created (issue #1391)

- PULL_REQUEST_CREATED, a new notification_type value for the warehouse audience, raised when a
  shipping request is accepted or a shop assembly batch is dispatched.

Downgrade mirrors 131: delete rows of the retiring type first, then recreate notification_type
without it.

Revision ID: 152
Revises: 151
Create Date: 2026-10-20
"""

from alembic import op

revision = "152"
down_revision = "151"
branch_labels = None
depends_on = None

# notification_type as it stands after 131.
_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'GP_WRITE_FAILED', 'RECEIVE_DRAFT_SUBMITTED', 'RECEIVE_DRAFT_REJECTED', "
    "'SHIPPING_REQUEST_REJECTED', 'CLASSIFICATION_CHANGED', 'SHOP_ASSEMBLY_REQUEST_REJECTED'"
)


def upgrade() -> None:
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'PULL_REQUEST_CREATED'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type::text = 'PULL_REQUEST_CREATED'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
