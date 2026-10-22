"""the generated PO document keeps only what the buyer typed of GP's figures (issue #1885)

- po_document_data.freight, miscellaneous, tax_amount and currency: nullable, with no server default.
  The dialog saved every field as if typed, so a document generated while GP's totals were still being
  read froze the fallbacks (freight from the order, misc 0, tax 0, CAD) and every later open preferred
  them to GP's. Null now means the buyer did not type it, and the dialog prefills GP's figure, as
  trade_discount already does (#1236). Existing rows keep their values: which of them were typed is not
  known.

Downgrade fills the nulls with the old defaults and restores NOT NULL and the server defaults.

Revision ID: 158
Revises: 157
Create Date: 2026-10-22
"""

import sqlalchemy as sa

from alembic import op

revision = "158"
down_revision = "157"
branch_labels = None
depends_on = None

_MONEY = ("freight", "miscellaneous", "tax_amount")


def upgrade() -> None:
    for column in _MONEY:
        op.alter_column(
            "po_document_data",
            column,
            existing_type=sa.Numeric(12, 2),
            nullable=True,
            server_default=None,
        )
    op.alter_column(
        "po_document_data",
        "currency",
        existing_type=sa.String(length=3),
        nullable=True,
        server_default=None,
    )


def downgrade() -> None:
    for column in _MONEY:
        op.execute(f"UPDATE po_document_data SET {column} = 0 WHERE {column} IS NULL")
        op.alter_column(
            "po_document_data",
            column,
            existing_type=sa.Numeric(12, 2),
            nullable=False,
            server_default="0",
        )
    op.execute("UPDATE po_document_data SET currency = 'CAD' WHERE currency IS NULL")
    op.alter_column(
        "po_document_data",
        "currency",
        existing_type=sa.String(length=3),
        nullable=False,
        server_default="CAD",
    )
