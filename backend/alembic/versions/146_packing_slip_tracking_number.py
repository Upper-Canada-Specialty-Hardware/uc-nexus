"""packing slips: a courier's tracking number of its own (issue #1725)

Asked for in the outbound supervisor's walkthrough review (#1720): the number a courier shipment is
traced by, as its own Delivery Request field rather than typed into carrier / tag / BOL. Nullable,
like every other header field; existing slips stay blank.

Revision ID: 146
Revises: 145
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "146"
down_revision = "145"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("packing_slips", sa.Column("tracking_number", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("packing_slips", "tracking_number")
