"""The GP PO LINE ITEM a SharePoint migration mark was bought on

Revision ID: 112
Revises: 111
Create Date: 2026-09-10

A migrated project quantity that the wizard could attach to a mirrored PO ties the schedule rows it
marks to that GP PO LINE ITEM rather than leaving them null-linked. The mark has to record the line
as well as the quantity: a `replace_schedule` re-import wipes the marked rows, and the re-apply has
to put the tie back on the same line rather than downgrading it to an unlinked marking.

Null on every mark written before this, and on every mark whose row named no purchase order - which
is the ordinary case and stays exactly as it was.
"""

import sqlalchemy as sa

from alembic import op

revision = "112"
down_revision = "111"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "sharepoint_migration_marks",
        sa.Column(
            "po_line_item_id",
            sa.Uuid(),
            sa.ForeignKey("po_line_items.id"),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("sharepoint_migration_marks", "po_line_item_id")
