"""custom item product codes are unique within their type ignoring case (issue #1342)

- uq_custom_inventory_items_type_code_ci: a unique index on (type_id, lower(product_code)), replacing
  the case-sensitive uq_custom_inventory_items_type_code. FR-101 and fr-101 under one type were two
  catalog rows, and stock split across the two codes.

Upgrade refuses, naming them, when a type already holds codes that differ only by case: which one to
keep is a person's call, because stock may already sit under either spelling. Downgrade restores the
case-sensitive constraint, which every row that satisfied the index also satisfies.

Revision ID: 134
Revises: 131
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "134"
down_revision = "131"
branch_labels = None
depends_on = None


def upgrade() -> None:
    clashes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT type_id, lower(product_code) AS code, count(*) AS n FROM custom_inventory_items "
                "GROUP BY type_id, lower(product_code) HAVING count(*) > 1"
            )
        )
        .all()
    )
    if clashes:
        named = ", ".join(f"{row.code} (type {row.type_id}, {row.n} rows)" for row in clashes)
        raise RuntimeError(
            "Custom item product codes differ only by case within a type, so they cannot be made unique "
            f"ignoring case: {named}. Merge or rename them first."
        )
    op.drop_constraint("uq_custom_inventory_items_type_code", "custom_inventory_items", type_="unique")
    op.create_index(
        "uq_custom_inventory_items_type_code_ci",
        "custom_inventory_items",
        ["type_id", sa.text("lower(product_code)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_custom_inventory_items_type_code_ci", table_name="custom_inventory_items")
    op.create_unique_constraint(
        "uq_custom_inventory_items_type_code", "custom_inventory_items", ["type_id", "product_code"]
    )
