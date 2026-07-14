"""Add po_document_data table + buyer_id on purchase_orders (issue #230)

po_document_data holds the per-PO gap fields the generated supplier PO document needs but Nexus
doesn't otherwise store (vendor mailing address, buyer name, currency, resolved ship-to block,
proposal number, GP-computed freight/misc/tax, tax label, required-by override, conditional-note
toggles), 1:1 with the PO. buyer_id captures the GP BUYERID picked in the Create/Register PO dialog
so the document's Buyer field pre-fills.

Revision ID: 048
Revises: 047
Create Date: 2026-07-14
"""

import sqlalchemy as sa

from alembic import op

revision = "048"
down_revision = "047"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("buyer_id", sa.String(length=15), nullable=True))

    op.create_table(
        "po_document_data",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("po_id", sa.Uuid(), nullable=False),
        sa.Column("vendor_address", sa.Text(), nullable=True),
        sa.Column("buyer_name", sa.String(), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=False, server_default="CAD"),
        sa.Column("ship_to", sa.Text(), nullable=True),
        sa.Column("shipping_method", sa.String(), nullable=True),
        sa.Column("proposal_number", sa.String(), nullable=True),
        sa.Column("freight", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("miscellaneous", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax_amount", sa.Numeric(12, 2), nullable=False, server_default="0"),
        sa.Column("tax_label", sa.String(), nullable=False, server_default="Taxes"),
        sa.Column("required_by_override", sa.Date(), nullable=True),
        sa.Column("include_fsc", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("include_usa_tariff", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("include_customs", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["po_id"], ["purchase_orders.id"]),
        sa.UniqueConstraint("po_id", name="uq_po_document_data_po_id"),
    )


def downgrade() -> None:
    op.drop_table("po_document_data")
    op.drop_column("purchase_orders", "buyer_id")
