"""Create vendors table; replace PO vendor_name/vendor_contact with vendor_id FK

Revision ID: 025
Revises: 024
Create Date: 2026-05-01
"""

import sqlalchemy as sa

from alembic import op

revision = "025"
down_revision = "024"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vendors",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("contact_name", sa.String(), nullable=True),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_vendors_name"),
    )

    op.add_column("purchase_orders", sa.Column("vendor_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_purchase_orders_vendor_id",
        "purchase_orders",
        "vendors",
        ["vendor_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index("ix_purchase_orders_vendor_id", "purchase_orders", ["vendor_id"])

    # Backfill: create a Vendor row per distinct non-null vendor_name, then map POs
    op.execute(
        """
        INSERT INTO vendors (id, name, created_at, updated_at)
        SELECT gen_random_uuid(), name, now(), now()
        FROM (
            SELECT DISTINCT vendor_name AS name
            FROM purchase_orders
            WHERE vendor_name IS NOT NULL
        ) AS src
        """
    )
    op.execute(
        """
        UPDATE purchase_orders
        SET vendor_id = v.id
        FROM vendors v
        WHERE v.name = purchase_orders.vendor_name
        """
    )

    op.drop_column("purchase_orders", "vendor_name")
    op.drop_column("purchase_orders", "vendor_contact")


def downgrade() -> None:
    op.add_column("purchase_orders", sa.Column("vendor_name", sa.String(), nullable=True))
    op.add_column("purchase_orders", sa.Column("vendor_contact", sa.String(), nullable=True))

    op.execute(
        """
        UPDATE purchase_orders
        SET vendor_name = v.name
        FROM vendors v
        WHERE v.id = purchase_orders.vendor_id
        """
    )

    op.drop_index("ix_purchase_orders_vendor_id", table_name="purchase_orders")
    op.drop_constraint("fk_purchase_orders_vendor_id", "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "vendor_id")

    op.drop_table("vendors")
