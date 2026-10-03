"""shipment method names are unique per company regardless of case (issue #1388)

The repository already refused a second "flatbed" beside "Flatbed", but with an unlocked read
before the write, while uq_shipment_methods_company_name compared names case-sensitively. Two
people adding "Flatbed" and "flatbed" at once both committed, which is two spellings of one
carrier. The constraint is replaced by a unique index on (company, lower(name)), so the database
holds the same rule the repository checks.

Upgrade refuses, naming them, when a company already has names that differ only by case: which one
to keep is a shipping department's call, not a migration's.

Revision ID: 136
Revises: 127
Create Date: 2026-10-03
"""

import sqlalchemy as sa

from alembic import op

revision = "136"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    clashes = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT company, lower(name) AS folded, string_agg(name, ', ' ORDER BY name) AS names "
                "FROM shipment_methods GROUP BY company, lower(name) HAVING count(*) > 1 "
                "ORDER BY company, folded"
            )
        )
        .all()
    )
    if clashes:
        listed = "; ".join(f"{row.company}: {row.names}" for row in clashes)
        raise RuntimeError(
            "Shipment method names that differ only by case must be merged or renamed before this "
            f"migration can run: {listed}"
        )
    op.drop_constraint("uq_shipment_methods_company_name", "shipment_methods", type_="unique")
    op.create_index(
        "uq_shipment_methods_company_lower_name",
        "shipment_methods",
        ["company", sa.text("lower(name)")],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_shipment_methods_company_lower_name", table_name="shipment_methods")
    op.create_unique_constraint("uq_shipment_methods_company_name", "shipment_methods", ["company", "name"])
