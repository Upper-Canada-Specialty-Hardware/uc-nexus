"""Per-project GP setup verdict (#425)

Revision ID: 075
Revises: 074
Create Date: 2026-07-30

Receiving PO0000070 in TUBC failed with eConnect 4612 "Invalid Account Index": the PO line carried
INVINDX=1617, copied from JC00701 (job 23093, cost code 210-200-2) when the WennSoft integration
registered it. 1617 does not exist in UBC/TUBC's GL00105 - it is a UCSH index, left by the pre-2023
UCSH -> UBC job replication which copied JC00701 account indexes raw. Production UBC holds 1504 such
rows across 62 jobs. A job-cost PO against any of them registers fine and can never be received.

Repairing GP is accounting's job. What Nexus owes is detection, so the gp_job_sync pass now asks the
relay for a per-job verdict and stamps it here:
  gp_setup_ok         - False quarantines the project's write actions
  gp_setup_detail     - JSON list of {cost_code, account_index}, so the banner names what is broken
  gp_setup_checked_at - when the stamp was taken, so a stale verdict is visible as stale

All three are NULLABLE and null is NOT a quarantine. Never-checked has to stay distinguishable from
checked-and-broken: the sync only runs while a relay is connected, and defaulting to False would mean
a relay outage - or a fresh database before its first pass - froze every project in Nexus. A down
relay already blocks the GP writes it is actually needed for; it must not also block importing a
schedule.

No index: the columns are read alongside the project row that was already being loaded, never
filtered on. `downgrade()` drops all three, losing only a verdict the next sync pass restamps.
"""

import sqlalchemy as sa

from alembic import op

revision = "075"
down_revision = "074"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("gp_setup_ok", sa.Boolean(), nullable=True))
    op.add_column("projects", sa.Column("gp_setup_detail", sa.Text(), nullable=True))
    op.add_column("projects", sa.Column("gp_setup_checked_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("projects", "gp_setup_checked_at")
    op.drop_column("projects", "gp_setup_detail")
    op.drop_column("projects", "gp_setup_ok")
