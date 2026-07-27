"""Pipeline notifications: three new signals and the key that dedupes one of them (#344)

Revision ID: 064
Revises: 063
Create Date: 2026-07-26

Slices 1-5 introduced states nobody was told about. A cart staged at 9am (#343) made an opening
assignable, but the assignment board only found out when somebody refreshed it. A replacement pull
completing (#341) gave a leaf its expectation back, and the only notification raised was for the
case where the leaf had *already shipped* - the ordinary case, where the assembler could go and fit
it, was silent. And a PR-REPL pull holds no reservation by design (#342: a deficiency cannot be
foreseen), so a replacement blocked on stock had nothing watching for the stock to arrive.

`notification_type` therefore gains:

- `ASSEMBLY_WORK_AVAILABLE` - openings became workable; addressed to the shop-assembly manager
  audience, because the consequence is that the board has unassigned work on it.
- `REPLACEMENT_ARRIVED` - a replacement landed for a leaf that has not shipped; addressed to the
  assembler holding that leaf.
- `PULL_UNBLOCKED` - a blocked replacement pull became coverable because a receive landed the stock;
  addressed to the warehouse.

`notifications.pull_request_id` is the other half. `PULL_UNBLOCKED` must not re-fire on every
subsequent receive, and the dedupe rule chosen is *one unread notification per pull*: raise it only
when the pull has no open one already. That needs an exact key on the row - matching the request
number inside `message` would hold only until somebody reworded the message, and this slice exists
precisely because states were knowable only by reading prose. The column is nullable and set only by
the pull-centred signals; `ON DELETE SET NULL` keeps the record when #325's reopen hard-deletes a
still-PENDING pull, since the notification is still a true statement about something that happened.

Additive; no backfill. Existing notifications keep a null `pull_request_id`, which reads as "this
one is not about a pull" - correct for every row written before this revision.

Downgrade deletes the rows using the three new labels (an enum recast fails on a value that is about
to stop existing), recreates `notification_type` without them, and drops the column and its index.
"""

import sqlalchemy as sa

from alembic import op

revision = "064"
down_revision = "063"
branch_labels = None
depends_on = None

_PULL_INDEX = "ix_notifications_pull_request_unread"

_NEW_NOTIFICATION_TYPES = ("ASSEMBLY_WORK_AVAILABLE", "REPLACEMENT_ARRIVED", "PULL_UNBLOCKED")

_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'REPLACEMENT_AFTER_SHIPMENT'"
)


def upgrade() -> None:
    op.add_column("notifications", sa.Column("pull_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_pull_request_id",
        "notifications",
        "pull_requests",
        ["pull_request_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        _PULL_INDEX,
        "notifications",
        ["pull_request_id", "type"],
        postgresql_where=sa.text("pull_request_id IS NOT NULL AND is_read = false"),
    )

    for label in _NEW_NOTIFICATION_TYPES:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{label}'")


def downgrade() -> None:
    labels = ", ".join(f"'{label}'" for label in _NEW_NOTIFICATION_TYPES)
    op.execute(f"DELETE FROM notifications WHERE type IN ({labels})")

    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")

    op.drop_index(_PULL_INDEX, table_name="notifications")
    op.drop_constraint("fk_notifications_pull_request_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "pull_request_id")
