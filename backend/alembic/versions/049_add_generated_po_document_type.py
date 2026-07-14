"""Add GENERATED_PO to the po_document_type enum (issue #230)

The finished supplier PO document Nexus now generates client-side can be saved back onto the PO as a
retained document; it gets its own document type so it's distinguishable from an uploaded GP doc or a
vendor acknowledgement.

Revision ID: 049
Revises: 048
Create Date: 2026-07-14
"""

from alembic import op

revision = "049"
down_revision = "048"
branch_labels = None
depends_on = None

_WITHOUT = "'PO_DOCUMENT', 'VENDOR_ACKNOWLEDGEMENT', 'MISCELLANEOUS'"


def upgrade() -> None:
    op.execute("ALTER TYPE po_document_type ADD VALUE IF NOT EXISTS 'GENERATED_PO'")


def downgrade() -> None:
    # Postgres cannot DROP a value from an enum in place, so recreate po_document_type without it
    # (mirrors migration 044). Any leftover generated-PO docs are removed first so the recast succeeds.
    op.execute("DELETE FROM po_documents WHERE document_type = 'GENERATED_PO'")
    op.execute("ALTER TYPE po_document_type RENAME TO po_document_type_old")
    op.execute(f"CREATE TYPE po_document_type AS ENUM ({_WITHOUT})")
    op.execute(
        "ALTER TABLE po_documents ALTER COLUMN document_type "
        "TYPE po_document_type USING document_type::text::po_document_type"
    )
    op.execute("DROP TYPE po_document_type_old")
