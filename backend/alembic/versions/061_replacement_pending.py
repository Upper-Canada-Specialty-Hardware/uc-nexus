"""Close the deficiency replacement loop (#341)

Revision ID: 061
Revises: 060
Create Date: 2026-07-26

Since #340 a unit found defective at the bench is condemned immediately: it goes back to inventory
flagged deficient and a PR-REPL pull line is minted for its replacement. Nothing ever brought that
replacement back to the leaf - `complete_pull_request` looked for openings hanging off the PR-REPL
pull request, found none (nothing hangs off a replacement PR), and completed as a no-op.

Closing the loop means reducing the leaf's `deficient_quantity` when the replacement arrives. On a
leaf still on the bench that is enough: the freed unit reappears as remaining work. On a leaf that is
already COMPLETED it would be corruption - completion's invariant is
`installed_quantity + deficient_quantity == quantity`, and quietly lowering `deficient_quantity`
would make a finished leaf read as un-dispositioned.

`shop_assembly_opening_items.replacement_pending_quantity` is the explicit third bucket that makes
the completed case representable. The three counts partition the line and the check constraint is
widened to `installed + deficient + replacement_pending <= quantity`, so a completed leaf whose
replacement has landed still sums to exactly `quantity` - it is complete, with a known unit of work
outstanding. Installing that unit moves it `replacement_pending -> installed`, again preserving the
sum, and appends/increments the `OpeningItemHardware` row.

Enum values that come with it:
- audit_action gains REPLACEMENT_RECEIVED (the pull completed and the expectation came back) and
  REPLACEMENT_INSTALL (it was fitted to an already-finished leaf).
- notification_type gains REPLACEMENT_AFTER_SHIPMENT, for a replacement that lands after its leaf
  has already left the building - the hardware is real and must not be stranded silently.

Downgrade folds any pending replacements back into `deficient_quantity` (the sum is unchanged, so
the narrower pre-#341 constraint still holds and the pre-#341 reading - "these units are condemned
and awaiting a replacement pull" - is restored), discards the new audit rows and notifications, and
recreates the two enums without the new labels, since Postgres cannot drop a label in place.
"""

import sqlalchemy as sa

from alembic import op

revision = "061"
down_revision = "060"
branch_labels = None
depends_on = None

_CONSTRAINT = "ck_shop_assembly_opening_items_progress_within_quantity"
_TABLE = "shop_assembly_opening_items"
_INDEX = "ix_shop_assembly_opening_items_replacement_pending"

_PROGRESS_WITHOUT_PENDING = (
    "installed_quantity >= 0 AND deficient_quantity >= 0 AND installed_quantity + deficient_quantity <= quantity"
)
_PROGRESS_WITH_PENDING = (
    "installed_quantity >= 0 AND deficient_quantity >= 0 AND replacement_pending_quantity >= 0 "
    "AND installed_quantity + deficient_quantity + replacement_pending_quantity <= quantity"
)

_AUDIT_ACTION_WITHOUT = (
    "'ADJUSTMENT', 'MOVE', 'UNLOCATE', 'RECEIVE', 'PULL_DEDUCTION', 'SPOT_CHECK', 'PUT_AWAY', "
    "'DESTOCK', 'ALLOCATE_FROM_STOCK', 'RECLASSIFY', 'REPORT_DEFICIENT', 'RESOLVE_DEFICIENT', "
    "'TRANSFER', 'RETURN', 'INSTALL_PROGRESS', 'ASSEMBLY_COMPLETE'"
)
_NOTIFICATION_TYPE_WITHOUT = (
    "'PULL_REQUEST_CANCELLED', 'PULL_REQUEST_COMPLETED', 'SHIPMENT_COMPLETED', 'INVENTORY_SHORTFALL'"
)


def upgrade() -> None:
    op.add_column(
        _TABLE,
        sa.Column("replacement_pending_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _PROGRESS_WITH_PENDING)
    op.create_index(
        _INDEX,
        _TABLE,
        ["shop_assembly_opening_id"],
        postgresql_where=sa.text("replacement_pending_quantity > 0"),
    )

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'REPLACEMENT_RECEIVED'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'REPLACEMENT_INSTALL'")
    op.execute("ALTER TYPE notification_type ADD VALUE IF NOT EXISTS 'REPLACEMENT_AFTER_SHIPMENT'")


def downgrade() -> None:
    # Rows first: an enum recast fails on any value that is about to stop existing, and the narrower
    # check constraint fails on any row still carrying a pending replacement.
    op.execute(
        f"UPDATE {_TABLE} SET deficient_quantity = deficient_quantity + replacement_pending_quantity, "
        "replacement_pending_quantity = 0 WHERE replacement_pending_quantity > 0"
    )
    op.execute("DELETE FROM inventory_audit_log WHERE action IN ('REPLACEMENT_RECEIVED', 'REPLACEMENT_INSTALL')")
    op.execute("DELETE FROM notifications WHERE type = 'REPLACEMENT_AFTER_SHIPMENT'")

    op.execute("ALTER TYPE audit_action RENAME TO audit_action_old")
    op.execute(f"CREATE TYPE audit_action AS ENUM ({_AUDIT_ACTION_WITHOUT})")
    op.execute("ALTER TABLE inventory_audit_log ALTER COLUMN action TYPE audit_action USING action::text::audit_action")
    op.execute("DROP TYPE audit_action_old")

    op.execute("ALTER TYPE notification_type RENAME TO notification_type_old")
    op.execute(f"CREATE TYPE notification_type AS ENUM ({_NOTIFICATION_TYPE_WITHOUT})")
    op.execute("ALTER TABLE notifications ALTER COLUMN type TYPE notification_type USING type::text::notification_type")
    op.execute("DROP TYPE notification_type_old")

    op.drop_index(_INDEX, table_name=_TABLE)
    op.drop_constraint(_CONSTRAINT, _TABLE, type_="check")
    op.create_check_constraint(_CONSTRAINT, _TABLE, _PROGRESS_WITHOUT_PENDING)
    op.drop_column(_TABLE, "replacement_pending_quantity")
