"""index the bell's newest-first notifications read (issue #1224)

- ix_notifications_project_created_at on notifications (project_id, created_at). The bell polls the
  five newest notifications a reader can see every 30s; the company scope filters on project_id and
  the read orders by created_at, which no index served, so every poll sorted the company's whole
  history.

Revision ID: 128
Revises: 127
Create Date: 2026-10-03
"""

from alembic import op

revision = "128"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_notifications_project_created_at", "notifications", ["project_id", "created_at"])


def downgrade() -> None:
    op.drop_index("ix_notifications_project_created_at", table_name="notifications")
