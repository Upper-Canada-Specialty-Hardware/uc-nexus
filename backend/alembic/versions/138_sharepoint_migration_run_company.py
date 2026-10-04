"""sharepoint migration runs record the company they wrote into (issue #1399)

A batch writes into one GP company (#1367), but the re-run guard (#1366) looked at any run at all,
so a second company's first migration was refused as a re-run. Each run now records its company and
the guard reads per company.

Backfill: a run is attributed to a company when every project its coverage marks touch belongs to
that one company. A run with no marks (stock-only) or with marks across companies stays null, and a
null run keeps guarding every company - an old run is never silently forgotten.

Revision ID: 138
Revises: 133
Create Date: 2026-10-04
"""

import sqlalchemy as sa

from alembic import op

revision = "138"
down_revision = "133"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sharepoint_migration_runs", sa.Column("company", sa.String(length=15), nullable=True))
    op.execute(
        sa.text(
            "UPDATE sharepoint_migration_runs AS r SET company = attributed.company "
            "FROM ("
            "  SELECT m.run_id, min(p.company) AS company "
            "  FROM sharepoint_migration_marks AS m JOIN projects AS p ON p.id = m.project_id "
            "  GROUP BY m.run_id HAVING count(DISTINCT p.company) = 1"
            ") AS attributed "
            "WHERE attributed.run_id = r.id"
        )
    )


def downgrade() -> None:
    op.drop_column("sharepoint_migration_runs", "company")
