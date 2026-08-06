"""Packing slip pinned to a receive draft

Revision ID: 087
Revises: 086
Create Date: 2026-08-06

A receive draft is a count made against a piece of paper that came off the truck (#504). Nothing
recorded which piece of paper, so a disputed count had nothing to check against.

The slip is a PO document, so this adds PACKING_SLIP to the po_document_type enum and a nullable FK
from receive_drafts to the document. The column is nullable in the database on purpose: drafts
raised before this requirement existed have no slip and must still load. Requiredness is enforced at
creation, not by the schema, so old rows stay readable while new ones cannot be made without one.

One slip per draft, held on the draft side: a PO with three deliveries carries three slips, each
pinned to the count it belongs to.

ALTER TYPE ... ADD VALUE cannot run inside a transaction block on older PostgreSQL and cannot be
reversed, so the downgrade drops the column and leaves the enum value in place. An orphaned enum
member is harmless; removing one means rewriting the type and every column that uses it.
"""

import sqlalchemy as sa

from alembic import op

revision = "087"
down_revision = "086"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("ALTER TYPE po_document_type ADD VALUE IF NOT EXISTS 'PACKING_SLIP'")
    op.add_column(
        "receive_drafts",
        sa.Column("packing_slip_document_id", sa.UUID(), nullable=True),
    )
    op.create_foreign_key(
        "fk_receive_drafts_packing_slip_document_id",
        "receive_drafts",
        "po_documents",
        ["packing_slip_document_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_receive_drafts_packing_slip_document_id", "receive_drafts", type_="foreignkey")
    op.drop_column("receive_drafts", "packing_slip_document_id")
    # PACKING_SLIP stays on the enum: removing a value means recreating the type and every column
    # that references it, which is a far larger risk than an unused member.
