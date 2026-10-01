"""a rejected shipping request tells its requester (issue #972)

Two things the requester notice needs:

- shipping_out_requests.created_by_user_id: the requester's Clerk user id, so the notice is owed to
  them by name, the way a rejected receive draft's is. Nullable: requests raised before this carry
  only a display name, and their notice goes to the shipping audience instead.
- SHIPPING_REQUEST_REJECTED, a new notification_type value.

Downgrade mirrors 079: delete rows of the retiring type first (an enum recast fails on a value that
is about to stop existing), then recreate notification_type without it.

Revision ID: 123
Revises: 122
Create Date: 2026-10-01
"""

import sqlalchemy as sa

from alembic import op

revision = "123"
down_revision = "122"
branch_labels = None
depends_on = None

# notification_type as it stands after 096.
_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'GP_WRITE_FAILED', 'RECEIVE_DRAFT_SUBMITTED', 'RECEIVE_DRAFT_REJECTED'"
)


def upgrade() -> None:
    op.add_column("shipping_out_requests", sa.Column("created_by_user_id", sa.String(), nullable=True))
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'SHIPPING_REQUEST_REJECTED'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type::text = 'SHIPPING_REQUEST_REJECTED'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
    op.drop_column("shipping_out_requests", "created_by_user_id")
