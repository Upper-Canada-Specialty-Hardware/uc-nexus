"""Phase 5: deficiency_reviews table + deficiency_resolution enum

Revision ID: 030
Revises: 029
Create Date: 2026-06-04
"""

import sqlalchemy as sa

from alembic import op

revision = "030"
down_revision = "029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    deficiency_resolution = sa.Enum(
        "SEND_TO_STOCK",
        "SCRAP",
        "REPAIR",
        "RETURN_TO_VENDOR",
        "LEAVE_AS_DEFICIENT",
        name="deficiency_resolution",
    )

    op.create_table(
        "deficiency_reviews",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "inventory_location_id",
            sa.Uuid(),
            sa.ForeignKey("inventory_locations.id"),
            nullable=True,
        ),
        sa.Column(
            "stock_item_id",
            sa.Uuid(),
            sa.ForeignKey("stock_items.id"),
            nullable=True,
        ),
        sa.Column("resolution", deficiency_resolution, nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("reason_text", sa.Text(), nullable=True),
        sa.Column("rma_reference", sa.String(100), nullable=True),
        sa.Column("reviewed_by", sa.String(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "resulting_stock_item_id",
            sa.Uuid(),
            sa.ForeignKey("stock_items.id"),
            nullable=True,
        ),
        sa.CheckConstraint(
            "(inventory_location_id IS NULL) <> (stock_item_id IS NULL)",
            name="ck_deficiency_reviews_exactly_one_source",
        ),
        sa.CheckConstraint(
            "quantity >= 1",
            name="ck_deficiency_reviews_quantity_positive",
        ),
    )
    op.create_index(
        "ix_deficiency_reviews_reviewed_at",
        "deficiency_reviews",
        ["reviewed_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_deficiency_reviews_reviewed_at", table_name="deficiency_reviews")
    op.drop_table("deficiency_reviews")
    op.execute("DROP TYPE deficiency_resolution")
