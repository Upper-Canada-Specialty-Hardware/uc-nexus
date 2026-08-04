"""Shipment containers and what is stacked in them

Revision ID: 083
Revises: 082
Create Date: 2026-08-03

Shipping out went straight from "these units are ship-ready" to a packing slip (#451). The work in
between - stacking a skid in an order the site can unload, building a shipment up over days out of
several containers - happened on the floor and was recorded nowhere, so nobody could see what was
already loaded without walking to it.

`packing_slip_id` is the whole lifecycle: null while the container is being built, stamped when a
shipment is confirmed, and from then on history. That is why there is no status column - the only
question ever asked is "has this left".

Nothing here moves inventory. The hardware left when its pull was picked (#367); a container records
how what is already staged is arranged for the truck.
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "083"
down_revision = "082"
branch_labels = None
depends_on = None


def upgrade() -> None:
    postgresql.ENUM(
        "SKID",
        "DOOR_CART",
        "BOX",
        "ENVELOPE",
        "BUNDLE",
        name="shipment_container_type",
    ).create(op.get_bind(), checkfirst=True)
    # Created above, so the column's reference must NOT try again - a bare postgresql.ENUM defaults
    # to emitting its own CREATE TYPE during create_table, which is a DuplicateObject on a fresh DB.
    container_type = postgresql.ENUM(
        "SKID",
        "DOOR_CART",
        "BOX",
        "ENVELOPE",
        "BUNDLE",
        name="shipment_container_type",
        create_type=False,
    )

    op.create_table(
        "shipment_containers",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("project_id", sa.UUID(), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("container_type", container_type, nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("packing_slip_id", sa.UUID(), sa.ForeignKey("packing_slips.id"), nullable=True),
        sa.Column("created_by", sa.String(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_shipment_containers_project_slip",
        "shipment_containers",
        ["project_id", "packing_slip_id"],
    )
    # One name per OPEN container per project. Shipped ones are excluded so next month's "Skid 1" is
    # not refused because a shipment in March used the name.
    op.create_index(
        "uq_shipment_containers_open_name",
        "shipment_containers",
        ["project_id", "name"],
        unique=True,
        postgresql_where=sa.text("packing_slip_id IS NULL"),
    )

    op.create_table(
        "shipment_container_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column(
            "shipment_container_id",
            sa.UUID(),
            sa.ForeignKey("shipment_containers.id", ondelete="CASCADE"),
            nullable=False,
        ),
        # Reuses the enum migration 004 created; this migration must not try to make it again.
        sa.Column(
            "item_type",
            postgresql.ENUM("LOOSE", "OPENING_ITEM", name="pull_request_item_type", create_type=False),
            nullable=False,
        ),
        sa.Column("opening_item_id", sa.UUID(), sa.ForeignKey("opening_items.id"), nullable=True),
        sa.Column("opening_number", sa.String(), nullable=True),
        sa.Column("leaf", sa.SmallInteger(), nullable=True),
        sa.Column("hardware_category", sa.String(), nullable=False),
        sa.Column("product_code", sa.String(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.CheckConstraint("quantity >= 1", name="ck_shipment_container_items_quantity_positive"),
    )
    op.create_index(
        "ix_shipment_container_items_container",
        "shipment_container_items",
        ["shipment_container_id"],
    )
    op.create_index(
        "ix_shipment_container_items_opening_item",
        "shipment_container_items",
        ["opening_item_id"],
    )


def downgrade() -> None:
    op.drop_table("shipment_container_items")
    op.drop_index("uq_shipment_containers_open_name", table_name="shipment_containers")
    op.drop_index("ix_shipment_containers_project_slip", table_name="shipment_containers")
    op.drop_table("shipment_containers")
    postgresql.ENUM(name="shipment_container_type").drop(op.get_bind(), checkfirst=True)
