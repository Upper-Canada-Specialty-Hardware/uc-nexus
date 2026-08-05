"""Rename po_document_data.proposal_number to quotation_number

Revision ID: 086
Revises: 085
Create Date: 2026-08-05

Quotation Number is the business term for the vendor quotation a PO is placed against (#507). The
column was named after "proposal", which is not what anyone calls it, and the generated supplier PO
printed the same wrong word.

Straight column rename, so every existing value survives. The document now labels it "Quote #".

Not to be confused with purchase_orders.vendor_quote_number, which is the quote reference captured
on the PO itself; this one is the number that prints on the generated document.
"""

import sqlalchemy as sa

from alembic import op

revision = "086"
down_revision = "085"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "po_document_data",
        "proposal_number",
        new_column_name="quotation_number",
        existing_type=sa.String(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "po_document_data",
        "quotation_number",
        new_column_name="proposal_number",
        existing_type=sa.String(),
        existing_nullable=True,
    )
