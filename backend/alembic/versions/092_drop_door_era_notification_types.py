"""Drop the four door-era notification types that no longer have a signal behind them

Revision ID: 092
Revises: 091
Create Date: 2026-08-10

Migration 091 removed the door-object model, and with it every code path that raised the four
notification types the deficiency/assembly/replacement loop depended on:

- REPLACEMENT_AFTER_SHIPMENT (#341) - a replacement pull completed for a leaf that had shipped.
- ASSEMBLY_WORK_AVAILABLE (#344) - openings became workable on the assembly floor.
- REPLACEMENT_ARRIVED (#344) - replacement hardware arrived for a leaf not yet shipped.
- PULL_UNBLOCKED (#344) - a blocked PR-REPL pull became coverable.

None was ever raised (they were introduced by 061/064 alongside a flow that shipped incomplete and
was then removed whole by 091), so no `notifications` row can carry any of them. The DELETE below is
belt-and-braces: an enum recast fails on a value in use, and stating the guard keeps the recast valid
even if some environment defied that.

Recast rather than a live-value drop because PostgreSQL cannot remove a label from an enum type in
place - the same rename/create/cast/drop shape 079's downgrade and 091 use. Downgrade re-adds the
four (append order; the enum's order is never depended on), so the migration-integrity down/up cycle
restores a superset the earlier migrations' downgrades can still recast through.
"""

from alembic import op

revision = "092"
down_revision = "091"
branch_labels = None
depends_on = None

_REMOVED = ("REPLACEMENT_AFTER_SHIPMENT", "ASSEMBLY_WORK_AVAILABLE", "REPLACEMENT_ARRIVED", "PULL_UNBLOCKED")

_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', "
    "'INVENTORY_SHORTFALL', 'GP_WRITE_FAILED', 'RECEIVE_DRAFT_SUBMITTED', "
    "'RECEIVE_DRAFT_REJECTED', 'RECEIVE_DECISION_REQUIRED'"
)


def upgrade() -> None:
    values = ", ".join(f"'{t}'" for t in _REMOVED)
    op.execute(f"DELETE FROM notifications WHERE type IN ({values})")
    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")


def downgrade() -> None:
    for value in _REMOVED:
        op.execute(f"ALTER TYPE notification_type ADD VALUE IF NOT EXISTS '{value}'")
