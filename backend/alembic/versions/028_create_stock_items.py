"""Phase 2: create stock_items table for non-stock (UCSH-owned) hardware

Revision ID: 028
Revises: 027
Create Date: 2026-06-04
"""

import sqlalchemy as sa

from alembic import op

revision = "028"
down_revision = "027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_items",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("deficient_quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("aisle", sa.String(20), nullable=True),
        sa.Column("bay", sa.String(20), nullable=True),
        sa.Column("bin", sa.String(20), nullable=True),
        sa.Column("received_at", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity >= 0", name="ck_stock_items_quantity_nonneg"),
        sa.CheckConstraint(
            "deficient_quantity >= 0",
            name="ck_stock_items_deficient_quantity_nonneg",
        ),
        sa.CheckConstraint(
            "deficient_quantity <= quantity",
            name="ck_stock_items_deficient_within_quantity",
        ),
    )
    # Drop server_default so the Python default (0) is the canonical source
    op.alter_column("stock_items", "deficient_quantity", server_default=None)

    op.create_index(
        "ix_stock_items_cat_code",
        "stock_items",
        ["hardware_category", "product_code"],
    )
    op.create_index("ix_stock_items_aisle", "stock_items", ["aisle"])


def downgrade() -> None:
    op.drop_index("ix_stock_items_aisle", table_name="stock_items")
    op.drop_index("ix_stock_items_cat_code", table_name="stock_items")
    op.drop_table("stock_items")
