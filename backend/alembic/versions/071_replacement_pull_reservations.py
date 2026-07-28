"""A replacement pull can hold a reservation of its own

Revision ID: 071
Revises: 070
Create Date: 2026-07-27

A PR-REPL pull was the one pull in the system that held no claim on inventory. The reasoning was
that nobody can reserve for a deficiency that has not happened yet - true at the moment the source
request was created, and irrelevant from the moment the assembler finds the defect. From then on the
replacement is a known, dated demand competing with requests created *after* it, and it lost every
time: it sat PENDING while the stock it was waiting for was claimed by somebody else, the approver
saw INSUFFICIENT, the PO was told to backfill again, and the loop repeated.

So the claim is minted where it becomes real: at the flag. That needs a third kind of holder on
`inventory_reservations`, because a replacement has no request behind it - the pull *is* the holder.

- `ReservationSource` gains `REPLACEMENT_PULL`.
- `pull_request_id` (nullable, CASCADE, indexed) is the FK that source writes to. CASCADE because
  `discard_pending_pull_request` hard-deletes a pull, and a claim outliving the only thing that
  could spend or release it is a permanently stranded reservation.
- `ck_inventory_reservations_source_matches_request` becomes three-way: each source requires exactly
  its own FK and nulls the other two, so the discriminator and the columns still cannot disagree.

The rewritten constraint compares `source::text` rather than the enum directly. PostgreSQL allows
`ALTER TYPE ... ADD VALUE` inside a transaction but refuses to *use* the new label until that
transaction commits, and creating a CHECK constraint validates it - so a bare
`source = 'REPLACEMENT_PULL'` would fail here and force a `COMMIT` in the middle of the migration,
breaking the atomicity of the whole `upgrade head`. Casting to text never touches the enum type.

A label cannot be dropped, so downgrade leaves the type alone and only unwinds the column, index and
constraint. It deletes any REPLACEMENT_PULL rows first: the old two-way constraint cannot express
them and would refuse to be created, and releasing those claims is the correct reading of "this
version does not reserve for replacements".
"""

import sqlalchemy as sa

from alembic import op

revision = "071"
down_revision = "070"
branch_labels = None
depends_on = None

_TABLE = "inventory_reservations"
_SOURCE_CHECK = "ck_inventory_reservations_source_matches_request"
_PULL_FK = "fk_inventory_reservations_pull_request"
_PULL_INDEX = "ix_inventory_reservations_pull_request"

_OLD_CONDITION = (
    "(source = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
    "AND shipping_out_request_id IS NULL) "
    "OR (source = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
    "AND shop_assembly_request_id IS NULL)"
)
_NEW_CONDITION = (
    "(source::text = 'SHOP_ASSEMBLY_REQUEST' AND shop_assembly_request_id IS NOT NULL "
    "AND shipping_out_request_id IS NULL AND pull_request_id IS NULL) "
    "OR (source::text = 'SHIPPING_OUT_REQUEST' AND shipping_out_request_id IS NOT NULL "
    "AND shop_assembly_request_id IS NULL AND pull_request_id IS NULL) "
    "OR (source::text = 'REPLACEMENT_PULL' AND pull_request_id IS NOT NULL "
    "AND shop_assembly_request_id IS NULL AND shipping_out_request_id IS NULL)"
)


def upgrade() -> None:
    op.execute("ALTER TYPE reservation_source ADD VALUE IF NOT EXISTS 'REPLACEMENT_PULL'")

    op.add_column(_TABLE, sa.Column("pull_request_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        _PULL_FK,
        _TABLE,
        "pull_requests",
        ["pull_request_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(_PULL_INDEX, _TABLE, ["pull_request_id"])

    op.drop_constraint(_SOURCE_CHECK, _TABLE, type_="check")
    op.create_check_constraint(_SOURCE_CHECK, _TABLE, _NEW_CONDITION)


def downgrade() -> None:
    op.drop_constraint(_SOURCE_CHECK, _TABLE, type_="check")
    op.execute(f"DELETE FROM {_TABLE} WHERE source::text = 'REPLACEMENT_PULL'")
    op.create_check_constraint(_SOURCE_CHECK, _TABLE, _OLD_CONDITION)

    op.drop_index(_PULL_INDEX, table_name=_TABLE)
    op.drop_constraint(_PULL_FK, _TABLE, type_="foreignkey")
    op.drop_column(_TABLE, "pull_request_id")
