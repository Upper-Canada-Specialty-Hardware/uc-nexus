"""Drop the Nexus-local vendors table

Revision ID: 085
Revises: 084
Create Date: 2026-08-05

GP owns vendors. Issue #200 already made that true on the wire - the GP vendor is picked live from
PM00200 through the relay at register time and snapshotted onto the PO as gp_vendor_id +
vendor_name_snapshot - but the local `vendors` table survived as an optional contact record hanging
off purchase_orders.vendor_id, carrying no GP meaning. It read as a second vendor registry: an admin
page created and deleted rows, and any signed-in PO user could invent a vendor that has no PM00200
counterpart. That is the drift 040 set out to end.

The backfill copies the local name into vendor_name_snapshot for POs that actually reached GP and
predate 040, so they keep the display name they were rendering through the FK fallback.

It is deliberately scoped to those: a DRAFT that was never registered has no GP vendor, and writing
a Nexus-local name into the GP snapshot column would make it look like one. That would contradict
the invariant the rest of this change establishes - vendor_name_snapshot IS the PM00200 pick, and a
draft shows no vendor at all - and the PO list would render an invented vendor as if GP had returned
it. Those drafts keep a null snapshot, which is the honest answer.
"""

import sqlalchemy as sa

from alembic import op

revision = "085"
down_revision = "084"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        UPDATE purchase_orders
        SET vendor_name_snapshot = v.name
        FROM vendors v
        WHERE v.id = purchase_orders.vendor_id
          AND purchase_orders.vendor_name_snapshot IS NULL
          AND purchase_orders.status <> 'DRAFT'
        """
    )

    op.drop_index("ix_purchase_orders_vendor_id", table_name="purchase_orders")
    op.drop_constraint("fk_purchase_orders_vendor_id", "purchase_orders", type_="foreignkey")
    op.drop_column("purchase_orders", "vendor_id")

    op.drop_table("vendors")


def downgrade() -> None:
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
