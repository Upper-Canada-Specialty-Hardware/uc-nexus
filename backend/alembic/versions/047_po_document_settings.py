"""Add po_document_settings table (issue #230)

Single-row admin boilerplate for the generated supplier PO document (tax numbers, mandatory
bullets, shipping accounts, customs-broker block, conditional FSC / USA-tariff notes, from-address,
footer). The row is seeded with guideline-doc defaults lazily by the repository's get_settings
get-or-create on first read, so this migration only creates the empty table.

Revision ID: 047
Revises: 046
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "047"
down_revision = "046"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "po_document_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("tax_numbers", sa.Text(), nullable=False),
        sa.Column("mandatory_bullets", sa.JSON(), nullable=False),
        sa.Column("shipping_accounts", sa.JSON(), nullable=False),
        sa.Column("customs_broker_block", sa.Text(), nullable=False),
        sa.Column("fsc_note", sa.Text(), nullable=False),
        sa.Column("usa_tariff_note", sa.Text(), nullable=False),
        sa.Column("usa_tariff_effective_until", sa.Date(), nullable=True),
        sa.Column("company_from_address", sa.Text(), nullable=False),
        sa.Column("payment_terms", sa.String(), nullable=False, server_default="Net 30"),
        sa.Column("confirm_with", sa.String(), nullable=False, server_default=""),
        sa.Column("footer_notes", sa.Text(), nullable=False),
        sa.Column("signature_note", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("po_document_settings")
