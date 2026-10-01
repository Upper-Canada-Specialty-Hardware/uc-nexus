"""classification changes say what they did (issue #1050)

- hardware_classification_changes.note: what had already gone out under the old classification and
  what saving changed. Nullable: rows written before this carry none.
- CLASSIFICATION_CHANGED, a new notification_type value for the Shop Assembly Manager.

Downgrade mirrors 123: delete rows of the retiring type first, then recreate notification_type
without it.

Revision ID: 126
Revises: 125
Create Date: 2026-10-01
"""

import sqlalchemy as sa

from alembic import op

revision = "126"
down_revision = "125"
branch_labels = None
depends_on = None

# notification_type as it stands after 123.
_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'GP_WRITE_FAILED', 'RECEIVE_DRAFT_SUBMITTED', 'RECEIVE_DRAFT_REJECTED', "
    "'SHIPPING_REQUEST_REJECTED'"
)


def upgrade() -> None:
    op.add_column("hardware_classification_changes", sa.Column("note", sa.Text(), nullable=True))
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'CLASSIFICATION_CHANGED'")


def downgrade() -> None:
    op.execute("DELETE FROM notifications WHERE type::text = 'CLASSIFICATION_CHANGED'")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
    op.drop_column("hardware_classification_changes", "note")
