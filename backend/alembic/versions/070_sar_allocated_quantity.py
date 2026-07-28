"""Shop-assembly checklist lines carry an allocated quantity as well as an owed one

Revision ID: 070
Revises: 069
Create Date: 2026-07-27

Shop assembly stops being all-or-nothing at creation. Until now a request that did not fit inside
available inventory was refused whole, so a leaf that was one hinge short could not be sent at all
and the twelve leaves behind it waited with it. The requester now assigns what is available to
leaves, partially-covered leaves stay in the request, and the send/don't-send call is theirs.

That needs two numbers on a checklist line where there was one:

- `quantity` keeps meaning **owed** - what the hardware schedule says this door leaf takes. It is
  never reduced by scarcity, because the schedule is the authority on what the leaf needs.
- `allocated_quantity` is what was actually claimed, reserved, pulled and will arrive on the cart.

Short is `quantity - allocated_quantity` and is **derived everywhere, stored nowhere**. There is no
short column and no short state, because a stored one would immediately start lying: the real
question "what is this leaf still missing" is answered by comparing the *current* schedule against
what is physically recorded on the leaf, which is the reallocation module's job. The number here is
evidence of what one request executed, not a backlog.

The progress buckets move with it. `installed + deficient + replacement_pending` now partitions
`allocated_quantity` rather than `quantity`: a short unit was never pulled, so there is nothing for
the assembler to install or condemn, and completion excuses it.

Backfill is exact rather than a default: every pre-feature request passed the all-or-nothing gate,
so by construction it was fully covered and `allocated_quantity = quantity` for every existing row.
The column is added with a server_default of 0 only so the NOT NULL add succeeds on a populated
table; the UPDATE sets the real values and the default is dropped immediately, so nothing later can
insert a silently-zero row and have it read as "fully short".

Downgrade drops the column and restores the old constraint. It is lossy in the honest direction:
rows where allocated < quantity would violate the old `... <= quantity` partition only if progress
had somehow exceeded owed, which it cannot, so no data has to be repaired first.
"""

import sqlalchemy as sa

from alembic import op

revision = "070"
down_revision = "069"
branch_labels = None
depends_on = None

_PROGRESS_CHECK = "ck_shop_assembly_opening_items_progress_within_quantity"
_OLD_CONDITION = (
    "installed_quantity >= 0 AND deficient_quantity >= 0 AND replacement_pending_quantity >= 0 "
    "AND installed_quantity + deficient_quantity + replacement_pending_quantity <= quantity"
)
_NEW_CONDITION = (
    "installed_quantity >= 0 AND deficient_quantity >= 0 AND replacement_pending_quantity >= 0 "
    "AND allocated_quantity >= 0 AND allocated_quantity <= quantity "
    "AND installed_quantity + deficient_quantity + replacement_pending_quantity <= allocated_quantity"
)


def upgrade() -> None:
    op.add_column(
        "shop_assembly_opening_items",
        sa.Column("allocated_quantity", sa.Integer(), nullable=False, server_default="0"),
    )
    # Every row that exists predates partial allocation and therefore cleared the all-or-nothing
    # creation gate: it was fully covered. Anything less would retroactively invent a shortfall on
    # hardware that is already on a cart or on a leaf.
    op.execute("UPDATE shop_assembly_opening_items SET allocated_quantity = quantity")
    op.alter_column("shop_assembly_opening_items", "allocated_quantity", server_default=None)

    op.drop_constraint(_PROGRESS_CHECK, "shop_assembly_opening_items", type_="check")
    op.create_check_constraint(_PROGRESS_CHECK, "shop_assembly_opening_items", _NEW_CONDITION)


def downgrade() -> None:
    op.drop_constraint(_PROGRESS_CHECK, "shop_assembly_opening_items", type_="check")
    op.create_check_constraint(_PROGRESS_CHECK, "shop_assembly_opening_items", _OLD_CONDITION)
    op.drop_column("shop_assembly_opening_items", "allocated_quantity")
