"""Durable audit for an adopted relay install (#353 PR B)

Revision ID: 066
Revises: 065
Create Date: 2026-07-27

The admin-armed adopt window rebinds a relay's credential from a connection that could not
authenticate. The window itself is in-memory and vanishes on the next deploy, so the only lasting
record of "this install was adopted, by whom, when" has to live on the row. Two nullable columns,
rendered in the admin grid.

Deliberately NOT an `inventory_audit_log` entry: that would need `RELAY_INSTALL` added to the
`audit_entity_type` PG enum, an ALTER TYPE with an awkward downgrade, to record exactly two facts
that belong on the install anyway.

Downgrade drops both columns; no data component, so it is exact.
"""

import sqlalchemy as sa

from alembic import op

revision = "066"
down_revision = "065"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("relay_installs", sa.Column("adopted_at", sa.DateTime(), nullable=True))
    op.add_column("relay_installs", sa.Column("adopted_by", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("relay_installs", "adopted_by")
    op.drop_column("relay_installs", "adopted_at")
