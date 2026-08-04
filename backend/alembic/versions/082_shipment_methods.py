"""Shipment methods, and the method a slip left under

Revision ID: 082
Revises: 081
Create Date: 2026-08-03

How a load travelled was nowhere on the Delivery Request (#451). The shipping department answers it
from the same handful of options every time - our truck, a named courier, customer pickup - so it is
a managed list rather than free text, which is what stops one carrier being spelled five ways across
a year of shipments.

`packing_slips.shipment_method` is a plain string, not a foreign key, in the same spirit as
`pickup_location` beside it: a reprint pulled up in a site dispute has to say what the driver was
told on the day, and a method renamed or retired since must not be able to rewrite or erase it.

Retiring a method is `is_active = False`; the table has no delete path that would orphan history.
"""

import sqlalchemy as sa

from alembic import op

revision = "082"
down_revision = "081"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "shipment_methods",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("name", name="uq_shipment_methods_name"),
    )
    op.add_column("packing_slips", sa.Column("shipment_method", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("packing_slips", "shipment_method")
    op.drop_table("shipment_methods")
