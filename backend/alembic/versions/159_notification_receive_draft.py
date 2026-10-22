"""a receive draft's waiting-for-approval notice names its draft (issue #1898)

- notifications.receive_draft_id: nullable FK to receive_drafts, ON DELETE SET NULL, with a partial index
  on the rows that carry it. Deleting a draft left its RECEIVE_DRAFT_SUBMITTED notice in every manager's
  bell, pointing at a queue the draft was no longer in, and nothing but the message's prose said which
  draft a notice was about. The delete now withdraws the notices by this key.

Additive; no backfill. Existing notices keep a null receive_draft_id and are not withdrawn by a delete:
which draft one was about is only written in its message.

Revision ID: 159
Revises: 158
Create Date: 2026-10-22
"""

import sqlalchemy as sa

from alembic import op

revision = "159"
down_revision = "158"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("receive_draft_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_receive_draft_id",
        "notifications",
        "receive_drafts",
        ["receive_draft_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notifications_receive_draft_id",
        "notifications",
        ["receive_draft_id"],
        postgresql_where=sa.text("receive_draft_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_receive_draft_id", table_name="notifications")
    op.drop_constraint("fk_notifications_receive_draft_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "receive_draft_id")
