"""po lines remember what had arrived when they were first registered (issue #1398)

A GP-born line's untied outstanding is ordered less the units received before it was registered (never
tied) less what is tied. `received_before_registration` records the first of those at registration.
Nullable, no backfill: lines registered earlier keep null and fall back to the old formula.
"""

import sqlalchemy as sa

from alembic import op

revision = "137"
down_revision = "133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("po_line_items", sa.Column("received_before_registration", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("po_line_items", "received_before_registration")
