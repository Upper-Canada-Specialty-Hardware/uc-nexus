"""Add projects.schedule_filename (#627)

Revision ID: 097
Revises: 096
Create Date: 2026-08-22

The source XML file name for a project's persisted hardware schedule, shown on the import wizard's
"use last uploaded" picker and the loaded-schedule card. Written on a fresh-parse finalize (initial
import, re-import from a new file, schedule replace); a hydrate-from-persisted finalize sends nothing,
so the stored name survives. Nullable - projects imported before this carry NULL and the wizard simply
omits the line. Downgrade drops the column.
"""

import sqlalchemy as sa

from alembic import op

revision = "097"
down_revision = "096"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("schedule_filename", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "schedule_filename")
