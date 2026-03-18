"""PO enhancements: nullable po_number, request_number, vendor_quote_number, po_documents

Revision ID: 015
Revises: 014
Create Date: 2026-03-18
"""

import sqlalchemy as sa

from alembic import op

revision = "015"
down_revision = "014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Make po_number nullable
    op.alter_column("purchase_orders", "po_number", existing_type=sa.String(50), nullable=True)

    # 2. Drop the old global unique index and constraint on po_number
    op.drop_index("ix_purchase_orders_po_number", table_name="purchase_orders")
    op.drop_constraint("purchase_orders_po_number_key", "purchase_orders", type_="unique")

    # 3. Add partial unique index: (project_id, po_number) WHERE po_number IS NOT NULL
    op.execute(
        "CREATE UNIQUE INDEX ix_purchase_orders_project_po_number "
        "ON purchase_orders (project_id, po_number) "
        "WHERE po_number IS NOT NULL"
    )

    # 4. Add request_number column — backfill existing rows first
    op.add_column("purchase_orders", sa.Column("request_number", sa.String(50), nullable=True))

    # Backfill: use po_number if set, otherwise generate sequential via CTE
    op.execute(
        "WITH numbered AS ("
        "  SELECT id, ROW_NUMBER() OVER (ORDER BY created_at) AS rn FROM purchase_orders"
        ") "
        "UPDATE purchase_orders SET request_number = COALESCE(po_number, 'PO-REQ-' || LPAD(numbered.rn::text, 3, '0')) "
        "FROM numbered WHERE purchase_orders.id = numbered.id"
    )

    # Now make it NOT NULL
    op.alter_column("purchase_orders", "request_number", existing_type=sa.String(50), nullable=False)

    # Add unique index on request_number
    op.create_index("ix_purchase_orders_request_number", "purchase_orders", ["request_number"], unique=True)

    # 5. Add vendor_quote_number column
    op.add_column("purchase_orders", sa.Column("vendor_quote_number", sa.String(), nullable=True))

    # 6. Create po_document_type enum + po_documents table via raw SQL
    # Using raw SQL to avoid SQLAlchemy auto-creating the enum type (which conflicts
    # with the model metadata already registering it during env.py import).
    op.execute(
        "DO $$ BEGIN "
        "  CREATE TYPE po_document_type AS ENUM ('PO_DOCUMENT', 'VENDOR_ACKNOWLEDGEMENT', 'MISCELLANEOUS'); "
        "EXCEPTION WHEN duplicate_object THEN NULL; "
        "END $$"
    )
    op.execute(
        "CREATE TABLE po_documents ("
        "  id UUID PRIMARY KEY, "
        "  po_id UUID NOT NULL REFERENCES purchase_orders(id), "
        "  file_name VARCHAR NOT NULL, "
        "  content_type VARCHAR NOT NULL, "
        "  file_size INTEGER NOT NULL, "
        "  document_type po_document_type NOT NULL, "
        "  s3_key VARCHAR NOT NULL, "
        "  uploaded_at TIMESTAMP NOT NULL"
        ")"
    )
    op.create_index("ix_po_documents_po_id", "po_documents", ["po_id"])


def downgrade() -> None:
    op.drop_index("ix_po_documents_po_id", table_name="po_documents")
    op.drop_table("po_documents")

    op.execute("DROP TYPE IF EXISTS po_document_type")

    op.drop_column("purchase_orders", "vendor_quote_number")

    op.drop_index("ix_purchase_orders_request_number", table_name="purchase_orders")
    op.drop_column("purchase_orders", "request_number")

    op.execute("DROP INDEX IF EXISTS ix_purchase_orders_project_po_number")

    # Re-create the old global unique index and constraint
    op.execute("UPDATE purchase_orders SET po_number = 'MIGRATED-' || id::text WHERE po_number IS NULL")
    op.alter_column("purchase_orders", "po_number", existing_type=sa.String(50), nullable=False)
    op.create_unique_constraint("purchase_orders_po_number_key", "purchase_orders", ["po_number"])
    op.create_index("ix_purchase_orders_po_number", "purchase_orders", ["po_number"], unique=True)
