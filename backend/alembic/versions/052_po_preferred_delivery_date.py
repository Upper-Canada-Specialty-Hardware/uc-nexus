"""PO preferred_delivery_date (issue #216)

The PM's requested date, captured at PO-request creation in the import wizard and editable only
while DRAFT. Distinct from expected_delivery_date, which is the vendor's answer and only enterable
after GP registration.

Revision ID: 052
Revises: 051
Create Date: 2026-07-16
"""

import sqlalchemy as sa

from alembic import op

revision = "052"
down_revision = "051"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("preferred_delivery_date", sa.Date(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "preferred_delivery_date")
