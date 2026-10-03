"""the generated PO document carries GP's trade discount (issue #1236)

- po_document_data.trade_discount: the trade discount (TRDISAMT) PO REGISTRATION wrote to GP, taken
  off the document's order total. Nullable: existing rows read null (never captured), so the dialog
  prefills GP's discount for them rather than a saved 0.

Downgrade drops the column.

Revision ID: 130
Revises: 129
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "130"
down_revision = "129"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "po_document_data",
        sa.Column("trade_discount", sa.Numeric(12, 2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("po_document_data", "trade_discount")
