"""warehouse names and codes are unique per company (issue #1256)

- uq_warehouses_name / uq_warehouses_code compared every tenant's buildings, so one company could not
  name a warehouse "Main" (or code it MAIN) because another company already had one, and the refusal
  revealed a building the caller cannot see. Codes are GP site codes, which each company's GP assigns
  on its own.
- Replaced by uq_warehouses_company_name / uq_warehouses_company_code on (company, name) and
  (company, code).

Downgrade restores the global constraints. It fails while two companies hold the same name or code,
which is the state this revision exists to allow; rename one first.

Numbered 132 and based on 127, master's head when it was written. Other open branches (128, 129)
also start from 127: whichever merges later re-points its down_revision at the one merged before it,
so the chain keeps a single head.

Revision ID: 132
Revises: 127
Create Date: 2026-10-03
"""

from alembic import op

revision = "132"
down_revision = "127"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_warehouses_name", "warehouses", type_="unique")
    op.drop_constraint("uq_warehouses_code", "warehouses", type_="unique")
    op.create_unique_constraint("uq_warehouses_company_name", "warehouses", ["company", "name"])
    op.create_unique_constraint("uq_warehouses_company_code", "warehouses", ["company", "code"])


def downgrade() -> None:
    op.drop_constraint("uq_warehouses_company_code", "warehouses", type_="unique")
    op.drop_constraint("uq_warehouses_company_name", "warehouses", type_="unique")
    op.create_unique_constraint("uq_warehouses_code", "warehouses", ["code"])
    op.create_unique_constraint("uq_warehouses_name", "warehouses", ["name"])
