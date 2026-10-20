"""what each gp company prints as itself: gp's name kept from the relay, and its own address (issue #1689)

One row per company code. The name is GP's, kept from the last relay hello that reported it so a document
printed while the relay is down still names the company; the address is typed per company. A company
with no row prints the shared PO document settings' from-address, as before.

Downgrade drops the table.

Revision ID: 151
Revises: 150
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "151"
down_revision = "150"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "company_letterheads",
        sa.Column("company", sa.String(length=15), primary_key=True),
        sa.Column("gp_name", sa.String(length=255), nullable=True),
        sa.Column("gp_name_seen_at", sa.DateTime(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("address_updated_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("company_letterheads")
