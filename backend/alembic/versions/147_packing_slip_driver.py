"""packing slips: the driver, by account and by name (issue #1726)

From the outbound supervisor's walkthrough review (#1720): a shipment on one of the company's trucks
names who drives it. `driver_user_id` is the Driver account; `driver_name` is its name when chosen,
kept so a reprint still says who drove. Both nullable; existing slips have no driver.

Revision ID: 147
Revises: 146
Create Date: 2026-10-19
"""

import sqlalchemy as sa

from alembic import op

revision = "147"
down_revision = "146"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("packing_slips", sa.Column("driver_user_id", sa.String(), nullable=True))
    op.add_column("packing_slips", sa.Column("driver_name", sa.String(), nullable=True))
    op.create_index("ix_packing_slips_driver_status", "packing_slips", ["driver_user_id", "status"])


def downgrade() -> None:
    op.drop_index("ix_packing_slips_driver_status", table_name="packing_slips")
    op.drop_column("packing_slips", "driver_name")
    op.drop_column("packing_slips", "driver_user_id")
