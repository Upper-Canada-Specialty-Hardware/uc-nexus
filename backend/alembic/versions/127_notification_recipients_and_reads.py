"""notifications have one recipient and a read state per person (issue #1111)

- notifications.recipient_user_id: the Clerk user id of a person-targeted notification. Until now
  that id was written into recipient_role, beside audience tags and display names.
- notifications.recipient_role becomes nullable and holds only an audience tag. Existing values are
  normalised: a Clerk user id moves to recipient_user_id, "Warehouse Staff" becomes WAREHOUSE, and a
  display name (the pull completed and cancelled signals wrote the requester's name) becomes the
  audience of the pull's source - SHIPPING or SHOP_ASSEMBLY - or WAREHOUSE when the pull is gone.
- ck_notifications_one_recipient: exactly one of the two is set.
- notification_reads: one row per person who has read a notification. Nobody can be credited with
  the reads made before this, so none are seeded.

Downgrade folds recipient_user_id back into recipient_role and drops the reads. The audience
normalisation is not undone: the names it replaced were never an addressable recipient.

Revision ID: 127
Revises: 126
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "127"
down_revision = "126"
branch_labels = None
depends_on = None

_AUDIENCES = "('PO', 'SHIPPING', 'SHOP_ASSEMBLY', 'SHOP_ASSEMBLY_MANAGER', 'WAREHOUSE', 'WAREHOUSE_MANAGER')"


def upgrade() -> None:
    op.add_column("notifications", sa.Column("recipient_user_id", sa.String(), nullable=True))
    op.alter_column("notifications", "recipient_role", existing_type=sa.String(), nullable=True)

    op.execute(
        "UPDATE notifications SET recipient_user_id = recipient_role, recipient_role = NULL "
        "WHERE recipient_role LIKE 'user\\_%'"
    )
    op.execute("UPDATE notifications SET recipient_role = 'WAREHOUSE' WHERE recipient_role = 'Warehouse Staff'")
    op.execute(
        "UPDATE notifications n SET recipient_role = CASE p.source::text "
        "WHEN 'SHIPPING_OUT' THEN 'SHIPPING' ELSE 'SHOP_ASSEMBLY' END "
        "FROM pull_requests p "
        f"WHERE n.pull_request_id = p.id AND n.recipient_role IS NOT NULL AND n.recipient_role NOT IN {_AUDIENCES}"
    )
    op.execute(
        "UPDATE notifications SET recipient_role = 'WAREHOUSE' "
        f"WHERE recipient_role IS NOT NULL AND recipient_role NOT IN {_AUDIENCES}"
    )

    op.create_check_constraint(
        "ck_notifications_one_recipient",
        "notifications",
        "(recipient_role IS NULL) <> (recipient_user_id IS NULL)",
    )
    op.create_index("ix_notifications_recipient_user_id", "notifications", ["recipient_user_id"])

    op.create_table(
        "notification_reads",
        sa.Column(
            "notification_id",
            sa.Uuid(),
            sa.ForeignKey("notifications.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("user_id", sa.String(), primary_key=True),
        sa.Column("read_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("notification_reads")
    op.drop_index("ix_notifications_recipient_user_id", table_name="notifications")
    op.drop_constraint("ck_notifications_one_recipient", "notifications", type_="check")
    op.execute("UPDATE notifications SET recipient_role = recipient_user_id WHERE recipient_role IS NULL")
    op.alter_column("notifications", "recipient_role", existing_type=sa.String(), nullable=False)
    op.drop_column("notifications", "recipient_user_id")
