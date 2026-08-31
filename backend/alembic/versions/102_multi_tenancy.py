"""Multi-tenancy: a GP company owns every project, warehouse, PO and catalog list (#637)

Revision ID: 102
Revises: 101
Create Date: 2026-08-31

A tenant IS a GP company (TUBC, UCSH, UBC). The relay protocol already carried `company` on every
call and the relay is multi-company capable; the single-company assumption lived here, in a schema
where nothing said which company a row belonged to.

Five tables get a direct `company` column - projects, warehouses, purchase_orders,
inventory_item_types, shipment_methods. Nothing else does: openings, hardware, inventory locations,
shipping requests, packing slips, shop assembly and buyer assignments inherit their scope through
their project, and warehouse locations, stock items and receive drafts through their warehouse.
Duplicating the column onto those would create two answers to "whose row is this" and no way to keep
them agreeing.

Every existing row is TUBC - the only company the product has ever run against - so the backfill is
a constant, and the columns land NOT NULL rather than nullable-with-a-meaning.

Two uniqueness keys stop being global and become per-company, because a global one locks the second
tenant out rather than merely inconveniencing it: a GP job number is unique within a company, not
across companies (024's `uq_projects_project_id`), and an inventory type code / shipment method name
is one company's own list. `relay_installs.company` becomes a `companies` JSON list, which is what
lets one install serve several companies the way the relay's own allowed_companies already does.
"""

import sqlalchemy as sa

from alembic import op

revision = "102"
down_revision = "101"
branch_labels = None
depends_on = None

DEFAULT_COMPANY = "TUBC"

# (table, index name) for the plain lookup index behind every tenant filter.
_COMPANY_TABLES = (
    "projects",
    "warehouses",
    "purchase_orders",
    "inventory_item_types",
    "shipment_methods",
)


def _add_company(table: str) -> None:
    """Add a NOT NULL company column in the three steps a populated table needs: nullable, backfill,
    tighten - the shape migration 033 used for warehouse_id."""
    op.add_column(table, sa.Column("company", sa.String(15), nullable=True))
    op.execute(f"UPDATE {table} SET company = '{DEFAULT_COMPANY}' WHERE company IS NULL")
    op.alter_column(table, "company", nullable=False)
    op.create_index(f"ix_{table}_company", table, ["company"])


def upgrade() -> None:
    for table in _COMPANY_TABLES:
        _add_company(table)

    # Projects also gain the archive flag. server_default so the column can land NOT NULL on a
    # populated table without a backfill pass of its own.
    op.add_column("projects", sa.Column("archived", sa.Boolean(), nullable=False, server_default=sa.false()))

    op.drop_constraint("uq_projects_project_id", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_company_project_id", "projects", ["company", "project_id"])

    op.drop_constraint("uq_inventory_item_types_code", "inventory_item_types", type_="unique")
    op.drop_constraint("uq_inventory_item_types_name", "inventory_item_types", type_="unique")
    op.create_unique_constraint("uq_inventory_item_types_company_code", "inventory_item_types", ["company", "code"])
    op.create_unique_constraint("uq_inventory_item_types_company_name", "inventory_item_types", ["company", "name"])

    op.drop_constraint("uq_shipment_methods_name", "shipment_methods", type_="unique")
    op.create_unique_constraint("uq_shipment_methods_company_name", "shipment_methods", ["company", "name"])

    # relay_installs.company -> companies (a JSON list). Backfilled from the single code so a live
    # relay keeps authenticating and serving exactly the company it already did.
    op.add_column("relay_installs", sa.Column("companies", sa.JSON(), nullable=True))
    op.execute("UPDATE relay_installs SET companies = json_build_array(company)")
    op.alter_column("relay_installs", "companies", nullable=False)
    op.drop_column("relay_installs", "company")


def downgrade() -> None:
    op.add_column("relay_installs", sa.Column("company", sa.String(), nullable=True))
    # The first entry is the one the single-company world served; an empty list degrades to the
    # default rather than leaving a NOT NULL column unfillable.
    op.execute("UPDATE relay_installs SET company = COALESCE(NULLIF(companies->>0, ''), '" + DEFAULT_COMPANY + "')")
    op.alter_column("relay_installs", "company", nullable=False)
    op.drop_column("relay_installs", "companies")

    op.drop_constraint("uq_shipment_methods_company_name", "shipment_methods", type_="unique")
    op.create_unique_constraint("uq_shipment_methods_name", "shipment_methods", ["name"])

    op.drop_constraint("uq_inventory_item_types_company_name", "inventory_item_types", type_="unique")
    op.drop_constraint("uq_inventory_item_types_company_code", "inventory_item_types", type_="unique")
    op.create_unique_constraint("uq_inventory_item_types_name", "inventory_item_types", ["name"])
    op.create_unique_constraint("uq_inventory_item_types_code", "inventory_item_types", ["code"])

    op.drop_constraint("uq_projects_company_project_id", "projects", type_="unique")
    op.create_unique_constraint("uq_projects_project_id", "projects", ["project_id"])

    op.drop_column("projects", "archived")

    for table in reversed(_COMPANY_TABLES):
        op.drop_index(f"ix_{table}_company", table_name=table)
        op.drop_column(table, "company")
