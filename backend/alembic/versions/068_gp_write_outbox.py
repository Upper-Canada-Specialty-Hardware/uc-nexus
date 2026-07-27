"""Durable outbox for GP writes that could not be dispatched (#353 PR E)

Revision ID: 068
Revises: 067
Create Date: 2026-07-27

`relay_call` raises the moment the relay socket is gone, so a backend deploy turns an in-flight
receive or PO registration into a failure a human has to notice and re-click. This table lets the
write be accepted, queued, and drained automatically when the relay reconnects.

The row carries the whole remainder of the pipeline as data: `payload` is exactly what the
resolver's `_prepare_*` built (it still runs at submit time, so validation fails fast in front of the
user), and `persist_context` holds the JSON-safe kwargs for the matching `_persist_*` helper - the
same helper the online path calls, so there is no second persist implementation.

Two indexes. `ix_gp_write_outbox_claim` on `(status, next_attempt_at)` is what the worker's claim
query rides. `ix_gp_write_outbox_entity_key` supports the per-entity FIFO subquery, which refuses a
row while an older unfinished row for the same PO is still queued - the rule that stops a receipt
being drained ahead of the registration of the PO it is against.

`status` is a String + CHECK rather than a PG enum, following migration 065: a CHECK is trivially
reversible, and this list will grow. `idempotency_key` is UNIQUE, tying a queued write to its
`gp_write_idempotency` ledger row and making a resubmit-while-queued return the same entry.

Downgrade drops the table. There is no data component and nothing else references it.
"""

import sqlalchemy as sa

from alembic import op

revision = "068"
down_revision = "067"
branch_labels = None
depends_on = None

_CLAIM_INDEX = "ix_gp_write_outbox_claim"
_ENTITY_INDEX = "ix_gp_write_outbox_entity_key"
_STATUS_CHECK = "ck_gp_write_outbox_status"
_STATUS_CONDITION = "status IN ('PENDING', 'IN_FLIGHT', 'SUCCEEDED', 'FAILED', 'CANCELLED')"


def upgrade() -> None:
    op.create_table(
        "gp_write_outbox",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("op", sa.String(), nullable=False),
        sa.Column("relay_op", sa.String(), nullable=False),
        sa.Column("company", sa.String(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("persist_context", sa.JSON(), nullable=False),
        sa.Column("entity_key", sa.String(), nullable=False),
        sa.Column("project_id", sa.Uuid(), nullable=True),
        sa.Column("label", sa.String(), nullable=False),
        sa.Column("requested_by", sa.String(), nullable=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(), nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_error_code", sa.String(), nullable=True),
        sa.Column("failure_kind", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("succeeded_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
        sa.CheckConstraint(_STATUS_CONDITION, name=_STATUS_CHECK),
    )
    op.create_index(_CLAIM_INDEX, "gp_write_outbox", ["status", "next_attempt_at"])
    op.create_index(_ENTITY_INDEX, "gp_write_outbox", ["entity_key"])


def downgrade() -> None:
    op.drop_index(_ENTITY_INDEX, table_name="gp_write_outbox")
    op.drop_index(_CLAIM_INDEX, table_name="gp_write_outbox")
    op.drop_table("gp_write_outbox")
