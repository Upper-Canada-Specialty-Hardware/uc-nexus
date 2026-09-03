"""Company-scope the jobless PO-number key, and widen the GP-fed cost columns

Revision ID: 105
Revises: 104
Create Date: 2026-09-03

Two failures the mirror hit the moment #667 pointed it at all twelve GP companies instead of one.

ix_purchase_orders_no_project_po_number was unique on po_number alone, wherever project_id was null.
A GP PO number is unique WITHIN a company and nowhere else, and TUCSH is a copy of UCSH down to its
PONUMBERs, so mirroring the second company's copy of a number the first already had was a duplicate
key every time. The index becomes (company, po_number) under the same predicate. The sibling
project-scoped index needs no such change: a project belongs to exactly one company already.

The cost columns were Numeric(10, 4), which caps at 999,999.9999. GP's own POP10110/POP30110.UNITCOST
is numeric(19, 5), so a single seven-figure GP line overflowed the column and took its whole PO's
upsert down with it. po_line_items.unit_cost is what the mirror writes; inventory_locations.unit_cost
and stock_items.unit_cost move with it, because resolve_project_combo_cost copies a PO line's cost onto
a re-materialized inventory row (a shipment return, a pull-cancel restock) and destock/transfer copy it
on from there - leaving those two narrow would just move the same overflow to receive time. All three
become Numeric(19, 5), matching GP. hardware_items' cost columns are TITAN-fed, not GP-fed, and stay.

Both halves of the downgrade are exact reversals and both can legitimately refuse to run on a database
that has since used the room they gave it: rebuilding the global index fails if two companies now
mirror the same jobless PO number, and narrowing the columns fails on a stored cost past 999,999.9999.
That is the honest behaviour - the alternative is deleting mirrored POs or silently truncating money.
"""

import sqlalchemy as sa

from alembic import op

revision = "105"
down_revision = "104"
branch_labels = None
depends_on = None

_OLD_INDEX = "ix_purchase_orders_no_project_po_number"
_NEW_INDEX = "ix_purchase_orders_company_no_project_po_number"
_NO_PROJECT_WHERE = sa.text("project_id IS NULL AND po_number IS NOT NULL")

# (table, column, nullable) for every cost column a GP-fed value can reach.
_COST_COLUMNS = (
    ("po_line_items", "unit_cost", False),
    ("inventory_locations", "unit_cost", True),
    ("stock_items", "unit_cost", True),
)


def upgrade() -> None:
    op.drop_index(_OLD_INDEX, table_name="purchase_orders")
    op.create_index(
        _NEW_INDEX,
        "purchase_orders",
        ["company", "po_number"],
        unique=True,
        postgresql_where=_NO_PROJECT_WHERE,
    )

    for table, column, nullable in _COST_COLUMNS:
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(10, 4),
            type_=sa.Numeric(19, 5),
            existing_nullable=nullable,
        )


def downgrade() -> None:
    for table, column, nullable in reversed(_COST_COLUMNS):
        op.alter_column(
            table,
            column,
            existing_type=sa.Numeric(19, 5),
            type_=sa.Numeric(10, 4),
            existing_nullable=nullable,
        )

    op.drop_index(_NEW_INDEX, table_name="purchase_orders")
    op.create_index(
        _OLD_INDEX,
        "purchase_orders",
        ["po_number"],
        unique=True,
        postgresql_where=_NO_PROJECT_WHERE,
    )
