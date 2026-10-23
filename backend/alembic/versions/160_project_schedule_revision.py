"""a finalize names the schedule revision it started from (issue #1918)

- projects.schedule_revision: counts the finalizes that wrote the project's hardware schedule. Every
  finalize wipes and re-inserts the unordered rows from what the wizard sends, so a tab working from a
  schedule someone has since replaced put its stale rows back and recreated openings the newer revision
  dropped. The wizard now sends the revision it loaded, and finalize refuses it when the count moved.

Backfill: a project that already has openings has a schedule, so it starts at 1; 0 is "no schedule yet",
which is what a wizard opened before a project's first import expects.

Revision ID: 160
Revises: 159
Create Date: 2026-10-22
"""

import sqlalchemy as sa

from alembic import op

revision = "160"
down_revision = "159"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column("schedule_revision", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute(
        "UPDATE projects SET schedule_revision = 1 "
        "WHERE EXISTS (SELECT 1 FROM openings WHERE openings.project_id = projects.id)"
    )


def downgrade() -> None:
    op.drop_column("projects", "schedule_revision")
