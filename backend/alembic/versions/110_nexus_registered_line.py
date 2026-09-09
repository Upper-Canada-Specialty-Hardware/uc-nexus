"""The NEXUS REGISTERED LINE flag on a PO line

Revision ID: 110
Revises: 109
Create Date: 2026-09-09

A GP PO LINE ITEM's Nexus copy either carries the schedule's own hardware category and product code or
it carries GP's item number and description. Until now the OPEN-POS SYNC told the two apart by the PO's
origin, which is the wrong grain: a GP-born PO can have its lines given a schedule identity one line at
a time, and from that moment the sync must leave those two fields alone on THAT line while still
overwriting them on its neighbours.

`nexus_registered` is that per-line answer. False everywhere by default; backfilled true on every line
of a PO Nexus drafted (origin NEXUS), because every one of those lines was written from a schedule.
"""

import sqlalchemy as sa

from alembic import op

revision = "110"
down_revision = "109"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "po_line_items",
        sa.Column("nexus_registered", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.execute(
        "UPDATE po_line_items SET nexus_registered = true "
        "WHERE po_id IN (SELECT id FROM purchase_orders WHERE origin = 'NEXUS')"
    )


def downgrade() -> None:
    op.drop_column("po_line_items", "nexus_registered")
