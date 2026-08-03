"""Add the three receive-approval notification types

Revision ID: 079
Revises: 078
Create Date: 2026-08-02

Migration 078 split a receive into a draft and an approval. Three moments in that loop are owed to
somebody who is not looking at the screen where they happened:

- RECEIVE_DRAFT_SUBMITTED: a counted delivery is waiting on a Warehouse Manager.
- RECEIVE_DRAFT_REJECTED: a manager sent one back, addressed to its author's Clerk user id.
- RECEIVE_DECISION_REQUIRED: hardware landed against somebody's PO and they have to say whether it
  stays in project inventory or ships out, addressed to that person's Clerk user id.

Downgrade mirrors 044 and 069 exactly: delete rows of the retiring types first (an enum recast fails
on a value that is about to stop existing), then recreate notification_type without them.
"""

from alembic import op

revision = "079"
down_revision = "078"
branch_labels = None
depends_on = None

_NEW_TYPES = ("RECEIVE_DRAFT_SUBMITTED", "RECEIVE_DRAFT_REJECTED", "RECEIVE_DECISION_REQUIRED")

_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'REPLACEMENT_AFTER_SHIPMENT', 'ASSEMBLY_WORK_AVAILABLE', "
    "'REPLACEMENT_ARRIVED', 'PULL_UNBLOCKED', 'GP_WRITE_FAILED'"
)


def upgrade() -> None:
    for new_type in _NEW_TYPES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{new_type}'")


def downgrade() -> None:
    values = ", ".join(f"'{t}'" for t in _NEW_TYPES)
    op.execute(f"DELETE FROM notifications WHERE type IN ({values})")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")
