"""The keep-or-ship decision moves to draft time

Revision ID: 090
Revises: 089
Create Date: 2026-08-06

The PO's creator is the only person who knows whether the site is waiting on a delivery or whether
it was ordered ahead of the schedule (#499). They were asked after the warehouse manager had already
approved the receive and booked it to inventory - by which point the hardware had been put away and
"send it straight back out" meant undoing work.

The question is raised when the count is submitted instead. `receive_record_id` becomes nullable and
`receive_draft_id` joins it: a decision now hangs off the draft that provoked it, and the receive
record is stamped on later, when approval actually books the receipt. Rows written before this
migration keep working unchanged - record-linked, draft null - because nothing reads one without
checking which it has.

The unique constraint on `receive_record_id` stays, and a matching one guards `receive_draft_id`:
one delivery, one decision, however many PO lines it covered.
"""

import sqlalchemy as sa

from alembic import op

revision = "090"
down_revision = "089"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("receive_decisions", "receive_record_id", existing_type=sa.UUID(), nullable=True)
    op.add_column("receive_decisions", sa.Column("receive_draft_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_receive_decisions_receive_draft",
        "receive_decisions",
        "receive_drafts",
        ["receive_draft_id"],
        ["id"],
    )
    op.create_unique_constraint(
        "uq_receive_decisions_receive_draft",
        "receive_decisions",
        ["receive_draft_id"],
    )
    # A decision with neither end is orphaned - it names no delivery anybody could act on.
    op.create_check_constraint(
        "ck_receive_decisions_has_source",
        "receive_decisions",
        "receive_record_id IS NOT NULL OR receive_draft_id IS NOT NULL",
    )


def downgrade() -> None:
    op.drop_constraint("ck_receive_decisions_has_source", "receive_decisions", type_="check")
    op.drop_constraint("uq_receive_decisions_receive_draft", "receive_decisions", type_="unique")
    op.drop_constraint("fk_receive_decisions_receive_draft", "receive_decisions", type_="foreignkey")
    # Draft-stage rows have no receive record to fall back on, so the column cannot go back to NOT
    # NULL while they exist. They are dropped: downgrading means the draft-time question is gone,
    # and approval raises the record-stage one again for anything still in flight.
    op.execute("DELETE FROM receive_decisions WHERE receive_record_id IS NULL")
    op.drop_column("receive_decisions", "receive_draft_id")
    op.alter_column("receive_decisions", "receive_record_id", existing_type=sa.UUID(), nullable=False)
