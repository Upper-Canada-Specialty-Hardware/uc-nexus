"""Persisted per-item assembly progress (#340)

Revision ID: 060
Revises: 059
Create Date: 2026-07-26

Assembly used to be an atomic, ephemeral event: the assembler's checklist lived only in the browser
until Mark Complete posted it, so a leaf half-built at the end of a shift lost everything. This adds
the two counters completion now reads instead:

- shop_assembly_opening_items.installed_quantity - units actually fitted to the leaf.
- shop_assembly_opening_items.deficient_quantity - units found defective and already sent through the
  deficiency flow (returned to inventory flagged deficient + a PR-REPL replacement pull).

Both default to 0, so every existing row starts un-dispositioned; a check constraint keeps them
non-negative and keeps their sum inside the planned quantity, which is what makes
`remaining = quantity - installed - deficient` safe to derive rather than store.

Three enum values come with it:
- assembly_status gains IN_PROGRESS - an opening with saved progress that is not finished.
- audit_action gains INSTALL_PROGRESS and ASSEMBLY_COMPLETE, and audit_entity_type gains
  SHOP_ASSEMBLY_OPENING, so a progress save is auditable against the work unit. Progress cannot hang
  off OPENING_ITEM - no OpeningItem exists until completion - and because saving progress and
  finishing the leaf are no longer the same call, the two moments need distinct actions.

Downgrade folds IN_PROGRESS openings back to PENDING (their saved counters go away with the columns,
which is exactly the pre-#340 behaviour), discards the progress audit rows, and recreates the three
enums without the new values - Postgres cannot drop an enum label in place.
"""

import sqlalchemy as sa

from alembic import op

revision = "060"
down_revision = "059"
branch_labels = None
depends_on = None

_ASSEMBLY_STATUS_WITHOUT = "'PENDING', 'COMPLETED'"
_AUDIT_ACTION_WITHOUT = (
    "'ADJUSTMENT', 'MOVE', 'UNLOCATE', 'RECEIVE', 'PULL_DEDUCTION', 'SPOT_CHECK', 'PUT_AWAY', "
    "'DESTOCK', 'ALLOCATE_FROM_STOCK', 'RECLASSIFY', 'REPORT_DEFICIENT', 'RESOLVE_DEFICIENT', "
    "'TRANSFER', 'RETURN'"
)
_AUDIT_ENTITY_TYPE_WITHOUT = "'INVENTORY_LOCATION', 'OPENING_ITEM', 'STOCK_ITEM'"


def upgrade() -> None:
    op.add_column(
        "shop_assembly_opening_items",
        sa.Column("installed_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "shop_assembly_opening_items",
        sa.Column("deficient_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_check_constraint(
        "ck_shop_assembly_opening_items_progress_within_quantity",
        "shop_assembly_opening_items",
        "installed_quantity >= 0 AND deficient_quantity >= 0 AND installed_quantity + deficient_quantity <= quantity",
    )

    op.execute("ALTER TYPE assembly_status ADD VALUE IF NOT EXISTS 'IN_PROGRESS'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'INSTALL_PROGRESS'")
    op.execute("ALTER TYPE audit_action ADD VALUE IF NOT EXISTS 'ASSEMBLY_COMPLETE'")
    op.execute("ALTER TYPE audit_entity_type ADD VALUE IF NOT EXISTS 'SHOP_ASSEMBLY_OPENING'")


def downgrade() -> None:
    # Rows first: an enum recast fails on any value that is about to stop existing. A half-built
    # opening becomes PENDING again, which is the only state pre-#340 code knows for unfinished work.
    op.execute("UPDATE shop_assembly_openings SET assembly_status = 'PENDING' WHERE assembly_status = 'IN_PROGRESS'")
    op.execute("DELETE FROM inventory_audit_log WHERE action IN ('INSTALL_PROGRESS', 'ASSEMBLY_COMPLETE')")
    op.execute("DELETE FROM inventory_audit_log WHERE entity_type = 'SHOP_ASSEMBLY_OPENING'")

    op.execute("ALTER TYPE assembly_status RENAME TO assembly_status_old")
    op.execute(f"CREATE TYPE assembly_status AS ENUM ({_ASSEMBLY_STATUS_WITHOUT})")
    op.execute(
        "ALTER TABLE shop_assembly_openings ALTER COLUMN assembly_status "
        "TYPE assembly_status USING assembly_status::text::assembly_status"
    )
    op.execute("DROP TYPE assembly_status_old")

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

    op.drop_constraint(
        "ck_shop_assembly_opening_items_progress_within_quantity",
        "shop_assembly_opening_items",
        type_="check",
    )
    op.drop_column("shop_assembly_opening_items", "deficient_quantity")
    op.drop_column("shop_assembly_opening_items", "installed_quantity")
