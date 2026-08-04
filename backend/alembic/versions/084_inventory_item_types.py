"""Inventory entity types, their custom attributes, and the catalog of items

Revision ID: 084
Revises: 083
Create Date: 2026-08-04

Frames, specialties and consumables are inventory the TITAN schedule never describes (#454), and
they still have to be bought, received, stored and shipped. These four tables are the catalog that
gives them the description the schedule would otherwise have supplied.

Nothing here alters the pipeline. A type's `code` is written into the existing free-text
`hardware_category` on a purchase order line and flows untouched from there, so `po_line_items`,
`inventory_locations`, `stock_items` and every table after them are unchanged and a frame stays as
fungible as a hinge.

The three types the issue names are seeded here rather than left to a first-run screen: the list
would otherwise be empty on a fresh database, and these three are the reason the feature exists.
Their attributes are deliberately NOT seeded - which ones matter is the warehouse's call, and
guessing would leave columns nobody asked for on every screen.
"""

import uuid
from datetime import datetime

import sqlalchemy as sa

from alembic import op

revision = "084"
down_revision = "083"
branch_labels = None
depends_on = None

SEEDED_TYPES = [
    ("FRAME", "Frames", 1),
    ("SPECIALTY", "Specialties", 2),
    ("CONSUMABLE", "Consumables", 3),
]


def upgrade() -> None:
    types = op.create_table(
        "inventory_item_types",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("code", sa.String(50), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("code", name="uq_inventory_item_types_code"),
        sa.UniqueConstraint("name", name="uq_inventory_item_types_name"),
    )

    op.create_table(
        "inventory_item_attributes",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("type_id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(100), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["type_id"], ["inventory_item_types.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("type_id", "name", name="uq_inventory_item_attributes_type_name"),
    )
    op.create_index("ix_inventory_item_attributes_type_id", "inventory_item_attributes", ["type_id"])

    op.create_table(
        "custom_inventory_items",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("type_id", sa.UUID(), nullable=False),
        sa.Column("product_code", sa.String(100), nullable=False),
        sa.Column("description", sa.String(255), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["type_id"], ["inventory_item_types.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("type_id", "product_code", name="uq_custom_inventory_items_type_code"),
    )
    op.create_index("ix_custom_inventory_items_type_id", "custom_inventory_items", ["type_id"])

    op.create_table(
        "custom_inventory_item_values",
        sa.Column("id", sa.UUID(), primary_key=True),
        sa.Column("item_id", sa.UUID(), nullable=False),
        sa.Column("attribute_id", sa.UUID(), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(["item_id"], ["custom_inventory_items.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["attribute_id"], ["inventory_item_attributes.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("item_id", "attribute_id", name="uq_custom_inventory_item_values_item_attr"),
    )
    op.create_index("ix_custom_inventory_item_values_item_id", "custom_inventory_item_values", ["item_id"])

    now = datetime.utcnow()
    op.bulk_insert(
        types,
        [
            {
                "id": uuid.uuid4(),
                "code": code,
                "name": name,
                "is_active": True,
                "sort_order": order,
                "created_at": now,
                "updated_at": now,
            }
            for code, name, order in SEEDED_TYPES
        ],
    )


def downgrade() -> None:
    op.drop_index("ix_custom_inventory_item_values_item_id", table_name="custom_inventory_item_values")
    op.drop_table("custom_inventory_item_values")
    op.drop_index("ix_custom_inventory_items_type_id", table_name="custom_inventory_items")
    op.drop_table("custom_inventory_items")
    op.drop_index("ix_inventory_item_attributes_type_id", table_name="inventory_item_attributes")
    op.drop_table("inventory_item_attributes")
    op.drop_table("inventory_item_types")
