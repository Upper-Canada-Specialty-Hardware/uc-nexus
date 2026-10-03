"""purchase orders carry the registration attempt on its way to GP (issue #1274)

Two windows registering one draft with the relay up each sent create_po under their own key, and GP
made two POs. `registering_key` / `registering_since` hold the one attempt in flight; a second is
refused until it settles or goes stale. Both nullable, no backfill: no PO is mid-registration now.
"""

import sqlalchemy as sa

from alembic import op

revision = "133"
down_revision = "136"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("purchase_orders", sa.Column("registering_key", sa.String(), nullable=True))
    op.add_column("purchase_orders", sa.Column("registering_since", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("purchase_orders", "registering_since")
    op.drop_column("purchase_orders", "registering_key")
