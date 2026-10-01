"""the usa tariff note is a permanent disclaimer: drop its effective-until date (issue #980)

The Generate PO Document toggle for the USA health-care tariff SA-code note showed an "effective until"
date and kept offering the note a year past it. The owner ruled the note a permanent potential
disclaimer, so the date is gone.

Downgrade re-adds the column empty: the date it held is not worth keeping.

Revision ID: 125
Revises: 124
Create Date: 2026-10-01
"""

import sqlalchemy as sa

from alembic import op

revision = "125"
down_revision = "124"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_column("po_document_settings", "usa_tariff_effective_until")


def downgrade() -> None:
    op.add_column("po_document_settings", sa.Column("usa_tariff_effective_until", sa.Date(), nullable=True))
