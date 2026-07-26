"""Replacement pull lines link back to the deficient assembly item (#339)

Revision ID: 059
Revises: 058
Create Date: 2026-07-26

Issue #339: report_deficiency_at_assembly mints a PR-REPL replacement pull line for a checklist item
flagged deficient at the bench, but the line carried nothing pointing back at the item that failed.
Add a nullable FK so a replacement can be traced to its ShopAssemblyOpeningItem - the hook the
replacement-loop closure hangs off - plus an index for the reverse lookup.

Additive and nullable, no backfill: pre-#339 replacement lines stay null (untraceable, as they are
today), and every non-replacement pull line stays null forever. The FK is created inline with the
column, so dropping the column in downgrade drops it too.
"""

import sqlalchemy as sa

from alembic import op

revision = "059"
down_revision = "058"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "pull_request_items",
        sa.Column(
            "sa_opening_item_id",
            sa.Uuid(),
            sa.ForeignKey("shop_assembly_opening_items.id"),
            nullable=True,
        ),
    )
    op.create_index(
        "ix_pull_request_items_sa_opening_item",
        "pull_request_items",
        ["sa_opening_item_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_pull_request_items_sa_opening_item", table_name="pull_request_items")
    op.drop_column("pull_request_items", "sa_opening_item_id")
