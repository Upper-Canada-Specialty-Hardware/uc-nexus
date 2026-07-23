"""Door-leaf awareness (#311): add leaf columns across schedule + assembly + shipping

Revision ID: 056
Revises: 055
Create Date: 2026-07-22

Epic #311: opening -> 1 or 2 door leaves -> hardware items. Six additive, nullable smallint
columns, no backfill (legacy rows stay null; a re-import re-derives the leaf).
- openings.leaf_count           = 1 (single) or 2 (pair); the "N of M leaves shipped" denominator.
- hardware_items.leaf           = 1 or 2 the item belongs to; null = frame / legacy.
- shop_assembly_openings.leaf   = which leaf this assembly work unit is for.
- opening_items.leaf            = which leaf this assembled inventory unit is.
- pull_request_items.leaf       = leaf snapshot on the pull line.
- packing_slip_items.leaf       = leaf snapshot on the immutable shipped record.
"""

import sqlalchemy as sa

from alembic import op

revision = "056"
down_revision = "055"
branch_labels = None
depends_on = None

# (table, column) added by this revision.
_COLUMNS = (
    ("openings", "leaf_count"),
    ("hardware_items", "leaf"),
    ("shop_assembly_openings", "leaf"),
    ("opening_items", "leaf"),
    ("pull_request_items", "leaf"),
    ("packing_slip_items", "leaf"),
)


def upgrade() -> None:
    for table, column in _COLUMNS:
        op.add_column(table, sa.Column(column, sa.SmallInteger(), nullable=True))


def downgrade() -> None:
    for table, column in reversed(_COLUMNS):
        op.drop_column(table, column)
