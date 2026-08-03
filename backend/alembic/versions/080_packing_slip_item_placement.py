"""Snapshot the assembled leaf's placement onto the shipped line

Revision ID: 080
Revises: 079
Create Date: 2026-08-03

The Delivery Request cut at confirm time names where each assembled leaf is going - building, floor
and location, read straight off the cart. A packing slip item recorded none of that, so the reprint
pulled up from the Shipments list rebuilt its MATERIAL DESCRIPTION from the stored items and dropped
the suffix. One shipment produced two different documents, and the reprint is the copy that gets
pulled up in a site dispute.

These three columns are the slip's own snapshot, in the same spirit as `leaf` and `opening_number`
beside them: the OpeningItem they came from can be re-placed or re-assembled years later, and the
paper the site signed has to keep saying where the leaf was headed on the day it left.

Nullable, and blank on a LOOSE line - loose hardware is fungible and has no placement to record.
Rows written before this migration keep printing without the suffix, which is what they were issued
with.
"""

import sqlalchemy as sa

from alembic import op

revision = "080"
down_revision = "079"
branch_labels = None
depends_on = None

_COLUMNS = ("building", "floor", "location")


def upgrade() -> None:
    for column in _COLUMNS:
        op.add_column("packing_slip_items", sa.Column(column, sa.String(), nullable=True))


def downgrade() -> None:
    for column in _COLUMNS:
        op.drop_column("packing_slip_items", column)
