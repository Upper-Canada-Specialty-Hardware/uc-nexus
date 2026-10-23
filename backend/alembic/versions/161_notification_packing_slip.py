"""a shipment's scheduled-for-pickup notice names its packing slip (issue #1942)

- notifications.packing_slip_id: nullable FK to packing_slips, ON DELETE SET NULL, with a partial index
  on the rows that carry it. Cancelling a shipment - by hand, or by its last returnable line coming back -
  left its "scheduled for pickup" notice in the warehouse's bell, sending somebody to load a truck that
  was no longer coming, and nothing but the message's prose said which slip a notice was about. A cancel
  now withdraws the notice by this key.

Additive; no backfill. Existing notices keep a null packing_slip_id and are not withdrawn by a cancel:
which slip one was about is only written in its message.

Revision ID: 161
Revises: 160
Create Date: 2026-10-22
"""

import sqlalchemy as sa

from alembic import op

revision = "161"
down_revision = "160"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("packing_slip_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_notifications_packing_slip_id",
        "notifications",
        "packing_slips",
        ["packing_slip_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "ix_notifications_packing_slip_id",
        "notifications",
        ["packing_slip_id"],
        postgresql_where=sa.text("packing_slip_id IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_packing_slip_id", table_name="notifications")
    op.drop_constraint("fk_notifications_packing_slip_id", "notifications", type_="foreignkey")
    op.drop_column("notifications", "packing_slip_id")
