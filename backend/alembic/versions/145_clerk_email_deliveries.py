"""receipt for every clerk email nexus sends, so a retried webhook never mails twice (issue #1690)

Clerk hands its sign-in code emails to `POST /webhooks/clerk/email` instead of mailing them; Nexus sends
each one through ucsh-mailer or SMTP2GO and writes one row per Clerk email id in the same transaction.
The row carries the id, the route and the time, and nothing a message said.

Downgrade drops the table.

Revision ID: 145
Revises: 144
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "145"
down_revision = "144"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "clerk_email_deliveries",
        sa.Column("clerk_email_id", sa.String(length=255), primary_key=True),
        sa.Column("route", sa.String(length=16), nullable=False),
        sa.Column("sent_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("route IN ('mailer', 'smtp2go')", name="ck_clerk_email_deliveries_route"),
    )


def downgrade() -> None:
    op.drop_table("clerk_email_deliveries")
