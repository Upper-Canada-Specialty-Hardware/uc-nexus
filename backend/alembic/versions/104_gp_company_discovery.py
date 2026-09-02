"""GP dictates the company list: drop relay_installs.companies

Revision ID: 104
Revises: 103
Create Date: 2026-09-01

102 turned the single `company` into a `companies` enrollment list, which kept the answer to "which
GP companies can this relay serve" inside Nexus - typed by an admin at provision time and backfilled
to ["TUBC"] for every existing row. Production could therefore only ever assign TUBC, and no screen
could offer a company nobody had thought to tick.

GP owns that list. The relay reads it from GP's company master and reports it on its hello frame, so
the backend learns it per connection instead of storing it: an install row is a credential and a
label, nothing more. An empty discovered list means the relay serves nothing, which is a live state
the gateway already refuses calls on - not a row to repair.

The downgrade repopulates the column rather than adding it empty, because 102's downgrade reads
`companies->>0` to rebuild the single `company` column.
"""

import sqlalchemy as sa

from alembic import op

revision = "104"
down_revision = "103"
branch_labels = None
depends_on = None

DEFAULT_COMPANY = "TUBC"


def upgrade() -> None:
    op.drop_column("relay_installs", "companies")


def downgrade() -> None:
    op.add_column("relay_installs", sa.Column("companies", sa.JSON(), nullable=True))
    op.execute("UPDATE relay_installs SET companies = '[\"" + DEFAULT_COMPANY + "\"]'")
    op.alter_column("relay_installs", "companies", nullable=False)
