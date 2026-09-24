"""projects carry the GP job as GP holds it (issue #730)

If GP contains it, GP owns it. The GP JOBS SYNC used to create a project for a job Nexus lacked and
then never look at it again, so a job renamed, re-addressed, moved to another customer, set inactive
or closed in GP stayed exactly as it was first adopted. These columns hold the rest of GP's job record
so every pass can overwrite them, and gp_job_state is what lets Nexus refuse a GP write against a job
GP itself will not accept.

Every column is nullable and nothing is backfilled: NULL gp_job_state is "never mirrored", which
refuses nothing, and the first pass against a relay that reports the full record fills the rest in.

Revision ID: 116
Revises: 115
Create Date: 2026-09-24
"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "116"
down_revision = "115"
branch_labels = None
depends_on = None

_STATES = ("ACTIVE", "INACTIVE", "CLOSED", "NOT_IN_GP")

_TEXT_COLUMNS = (
    "customer_number",
    "job_address_code",
    "billto_address_code",
    "address2",
    "country",
    "division",
    "tax_schedule_id",
    "use_tax_schedule_id",
    "estimator_id",
    "estimator_name",
    "ws_manager_id",
    "ws_manager_name",
)

_DATE_COLUMNS = (
    "gp_closed_date",
    "gp_created_date",
    "schedule_start_date",
    "scheduled_completion_date",
    "bid_due_date",
)

_MONEY_COLUMNS = (
    "orig_contract_amount",
    "contract_to_date",
    "total_actual_cost",
    "billed_amount_ttd",
    "retention_amount_ttd",
    "net_billed_ttd",
)


def upgrade() -> None:
    postgresql.ENUM(*_STATES, name="gp_job_state").create(op.get_bind(), checkfirst=True)
    op.add_column(
        "projects",
        sa.Column("gp_job_state", postgresql.ENUM(*_STATES, name="gp_job_state", create_type=False), nullable=True),
    )
    op.add_column("projects", sa.Column("gp_missing_since", sa.DateTime(), nullable=True))
    for name in _TEXT_COLUMNS:
        op.add_column("projects", sa.Column(name, sa.String(), nullable=True))
    for name in _DATE_COLUMNS:
        op.add_column("projects", sa.Column(name, sa.Date(), nullable=True))
    for name in _MONEY_COLUMNS:
        op.add_column("projects", sa.Column(name, sa.Numeric(19, 5), nullable=True))


def downgrade() -> None:
    for name in (*_MONEY_COLUMNS, *_DATE_COLUMNS, *_TEXT_COLUMNS, "gp_missing_since", "gp_job_state"):
        op.drop_column("projects", name)
    op.execute("DROP TYPE IF EXISTS gp_job_state")
