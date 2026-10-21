"""clerk email receipts: ucsh-mailer is the only route (issue #1810)

The product owner ruled Clerk's email codes are for ucsh.com users only and dropped the SMTP2GO fallback
for addresses outside the company, so a receipt's route can only be 'mailer'. No 'smtp2go' row can exist:
SMTP2GO was never configured on any deployment, so every send through it failed and left no receipt.

Downgrade widens the check back to both routes.

Revision ID: 156
Revises: 155
Create Date: 2026-10-21
"""

from alembic import op

revision = "156"
down_revision = "155"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("ck_clerk_email_deliveries_route", "clerk_email_deliveries", type_="check")
    op.create_check_constraint("ck_clerk_email_deliveries_route", "clerk_email_deliveries", "route = 'mailer'")


def downgrade() -> None:
    op.drop_constraint("ck_clerk_email_deliveries_route", "clerk_email_deliveries", type_="check")
    op.create_check_constraint(
        "ck_clerk_email_deliveries_route", "clerk_email_deliveries", "route IN ('mailer', 'smtp2go')"
    )
