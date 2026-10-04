"""warehouse, item type and attribute names and codes are unique regardless of case (issue #1402)

The repositories already refused "main" beside "Main" (and the same for item type names and codes
and attribute names), but with an unlocked read before the write, while the unique constraints
compared case-sensitively. Two people adding "Main" and "main" at once both committed. Each
constraint is replaced by a unique index on the lower-cased column, so the database holds the same
rule the repositories check (the class #1342 and #1388 closed for product codes and shipment methods).

Upgrade refuses, naming them, when existing rows already differ only by case: which spelling to
keep is a person's call, not a migration's.

Revision ID: 139
Revises: 133
Create Date: 2026-10-04
"""

import sqlalchemy as sa

from alembic import op

revision = "139"
down_revision = "133"
branch_labels = None
depends_on = None

# (table, scope column, value column, old constraint, new index)
_RULES = [
    ("warehouses", "company", "name", "uq_warehouses_company_name", "uq_warehouses_company_lower_name"),
    ("warehouses", "company", "code", "uq_warehouses_company_code", "uq_warehouses_company_lower_code"),
    (
        "inventory_item_types",
        "company",
        "name",
        "uq_inventory_item_types_company_name",
        "uq_inventory_item_types_company_lower_name",
    ),
    (
        "inventory_item_types",
        "company",
        "code",
        "uq_inventory_item_types_company_code",
        "uq_inventory_item_types_company_lower_code",
    ),
    (
        "inventory_item_attributes",
        "type_id",
        "name",
        "uq_inventory_item_attributes_type_name",
        "uq_inventory_item_attributes_type_lower_name",
    ),
]


def upgrade() -> None:
    bind = op.get_bind()
    problems = []
    for table, scope, column, _old, _new in _RULES:
        rows = bind.execute(
            sa.text(
                f"SELECT {scope}::text AS scope, string_agg({column}, ', ' ORDER BY {column} COLLATE \"C\") AS vals "
                f"FROM {table} GROUP BY {scope}, lower({column}) HAVING count(*) > 1 ORDER BY 1, 2"
            )
        ).all()
        problems += [f"{table}.{column} ({row.scope}): {row.vals}" for row in rows]
    if problems:
        raise RuntimeError(
            "Values that differ only by case must be merged or renamed before this migration can run: "
            + "; ".join(problems)
        )
    for table, scope, column, old, new in _RULES:
        op.drop_constraint(old, table, type_="unique")
        op.create_index(new, table, [scope, sa.text(f"lower({column})")], unique=True)


def downgrade() -> None:
    for table, scope, column, old, new in reversed(_RULES):
        op.drop_index(new, table_name=table)
        op.create_unique_constraint(old, table, [scope, column])
