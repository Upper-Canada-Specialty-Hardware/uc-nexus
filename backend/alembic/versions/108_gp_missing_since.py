"""When the mirror first missed a PO in both GP tables

Revision ID: 108
Revises: 107
Create Date: 2026-09-04

The closure sweep re-reads by number whatever left GP's open table. A number the relay reports as being
in NEITHER table has been deleted outright in GP, and the register kept showing it as an outstanding PO
forever. It is cancelled now, the same way a GP void is - but only on the SECOND consecutive pass that
cannot find it, because a single miss is also what a PO being edited in GP mid-pass looks like.

`gp_missing_since` is that guard: the pass start time of the first miss, cleared the moment the PO
comes back from GP in either table. Nullable, null on every existing row, which is "GP still has it".
"""

import sqlalchemy as sa

from alembic import op

revision = "108"
down_revision = "107"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("gp_missing_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "gp_missing_since")
