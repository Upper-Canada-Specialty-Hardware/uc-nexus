"""pull requests record who started the pick by user id (issue #1356)

- pull_requests.assigned_to_user_id: the Clerk user id of the person who started the pick. The pick
  page decided who the pull is locked to by comparing assigned_to, a display name, with the viewer's
  name - two people with one name, or a renamed person, got it wrong. Nullable: pulls started before
  this keep only the name, and readers fall back to it.

Downgrade drops the column; assigned_to is untouched either way.

Revision ID: 135
Revises: 127
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "135"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("pull_requests", sa.Column("assigned_to_user_id", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("pull_requests", "assigned_to_user_id")
