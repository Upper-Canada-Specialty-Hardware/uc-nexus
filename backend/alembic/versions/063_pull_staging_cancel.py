"""Per-opening pull staging + pull cancel/restock (#343)

Revision ID: 063
Revises: 062
Create Date: 2026-07-26

The warehouse stages a pull cart by cart, opening by opening, and the system only knew "pulled" or
"not pulled" for the whole request - so an opening whose hardware was on a cart at 9am was not
assignable until the last opening of the pull was picked at 4pm. Staging becomes per opening
(`shop_assembly_openings.pull_status`, which already existed), and this migration adds the two
columns that record *when* and *by whom*, since the pull's own `completed_at` can no longer answer
that question for an individual cart.

The other half is the way back. Once a pull was approved there was no way out: inventory was
deducted, and `PullRequestStatus.CANCELLED` was an enum value nothing ever set. Cancelling returns
the hardware to the shelf and sends the source request back to PENDING for re-acceptance - which
runs straight into `request_number` being globally unique on `pull_requests`, because re-accepting
mints a pull carrying the same number. (#325's reopen path dodged this by hard-deleting the pull; a
cancellation has to keep it.) The plain unique constraint is therefore replaced with a **partial**
unique index excluding cancelled rows: the number identifies the *live* pull for a request, which is
what every lookup on it actually means.

Columns and enum values:
- `shop_assembly_openings.staged_at` / `staged_by` - nullable, backfilled for nothing; existing
  PULLED openings simply have no staging stamp, which is honest (they were staged wholesale).
- `pull_requests.cancelled_by` / `cancellation_reason` - the actor and reason, alongside the
  `cancelled_at` that already existed, mirroring how a request rejection records itself.
- `audit_action` gains PULL_STAGED, PULL_RESTOCK, PULL_CANCELLED; `audit_entity_type` gains
  PULL_REQUEST (a cancellation is an event about the pull, not about any one inventory row).

Downgrade drops the columns and the new audit rows, recreates both enums without the new labels
(Postgres cannot drop a label in place), and restores the plain unique constraint - de-duplicating
first, by suffixing any cancelled row whose number a live row also carries, since that is precisely
the state this migration made reachable.
"""

import sqlalchemy as sa

from alembic import op

revision = "063"
down_revision = "062"
branch_labels = None
depends_on = None

_LIVE_NUMBER_INDEX = "uq_pull_requests_request_number_live"
_LEGACY_NUMBER_CONSTRAINT = "pull_requests_request_number_key"

_AUDIT_ACTION_WITHOUT = (
    "'ADJUSTMENT', 'MOVE', 'UNLOCATE', 'RECEIVE', 'PULL_DEDUCTION', 'SPOT_CHECK', 'PUT_AWAY', "
    "'DESTOCK', 'ALLOCATE_FROM_STOCK', 'RECLASSIFY', 'REPORT_DEFICIENT', 'RESOLVE_DEFICIENT', "
    "'TRANSFER', 'RETURN', 'INSTALL_PROGRESS', 'ASSEMBLY_COMPLETE', 'REPLACEMENT_RECEIVED', "
    "'REPLACEMENT_INSTALL'"
)
_AUDIT_ENTITY_TYPE_WITHOUT = "'INVENTORY_LOCATION', 'OPENING_ITEM', 'STOCK_ITEM', 'SHOP_ASSEMBLY_OPENING'"


def upgrade() -> None:
    op.add_column("shop_assembly_openings", sa.Column("staged_at", sa.DateTime(), nullable=True))
    op.add_column("shop_assembly_openings", sa.Column("staged_by", sa.String(), nullable=True))

    op.add_column("pull_requests", sa.Column("cancelled_by", sa.String(), nullable=True))
    op.add_column("pull_requests", sa.Column("cancellation_reason", sa.String(500), nullable=True))

    # Swap the global uniqueness of request_number for uniqueness among live pulls only.
    op.drop_constraint(_LEGACY_NUMBER_CONSTRAINT, "pull_requests", type_="unique")
    op.create_index(
        _LIVE_NUMBER_INDEX,
        "pull_requests",
        ["request_number"],
        unique=True,
        postgresql_where=sa.text("status <> 'CANCELLED'"),
    )

    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'PULL_STAGED'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'PULL_RESTOCK'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'PULL_CANCELLED'")
    op.execute("ALTER TYPE audit_entity_type ADD VALUE IF NOT EXISTS 'PULL_REQUEST'")


def downgrade() -> None:
    # Rows first: an enum recast fails on any value that is about to stop existing.
    op.execute("DELETE FROM inventory_audit_log WHERE action IN ('PULL_STAGED', 'PULL_RESTOCK', 'PULL_CANCELLED')")
    op.execute("DELETE FROM inventory_audit_log WHERE entity_type = 'PULL_REQUEST'")

    op.execute("ALTER TYPE audit_action RENAME TO audit_action_old")
    op.execute(f"CREATE TYPE audit_action AS ENUM ({_AUDIT_ACTION_WITHOUT})")
    op.execute("ALTER TABLE inventory_audit_log ALTER COLUMN action TYPE audit_action USING action::text::audit_action")
    op.execute("DROP TYPE audit_action_old")

    op.execute("ALTER TYPE audit_entity_type RENAME TO audit_entity_type_old")
    op.execute(f"CREATE TYPE audit_entity_type AS ENUM ({_AUDIT_ENTITY_TYPE_WITHOUT})")
    op.execute(
        "ALTER TABLE inventory_audit_log ALTER COLUMN entity_type "
        "TYPE audit_entity_type USING entity_type::text::audit_entity_type"
    )
    op.execute("DROP TYPE audit_entity_type_old")

    op.drop_index(_LIVE_NUMBER_INDEX, table_name="pull_requests")
    # A cancelled pull may legitimately share its number with the live pull a re-accept minted -
    # that is the whole point of the partial index. Global uniqueness cannot express it, so retire
    # the cancelled row's number rather than lose the row. Deterministic and self-describing, so the
    # history stays readable.
    op.execute(
        """
        UPDATE pull_requests p
           SET request_number = left(p.request_number, 41) || '-X' || left(replace(p.id::text, '-', ''), 8)
         WHERE p.status = 'CANCELLED'
           AND EXISTS (
                 SELECT 1 FROM pull_requests q
                  WHERE q.request_number = p.request_number AND q.id <> p.id
               )
        """
    )
    op.create_unique_constraint(_LEGACY_NUMBER_CONSTRAINT, "pull_requests", ["request_number"])

    op.drop_column("pull_requests", "cancellation_reason")
    op.drop_column("pull_requests", "cancelled_by")
    op.drop_column("shop_assembly_openings", "staged_by")
    op.drop_column("shop_assembly_openings", "staged_at")
