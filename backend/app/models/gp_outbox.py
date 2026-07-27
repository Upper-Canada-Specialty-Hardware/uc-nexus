"""Durable queue for GP writes that could not be dispatched (#353 PR E)."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from . import Base

# Terminal-ish classification for a FAILED row, so the queue UI can say what a human must do.
FAILURE_KINDS = ("gp_rejected", "ambiguous", "persist_failed", "exhausted")
STATUSES = ("PENDING", "IN_FLIGHT", "SUCCEEDED", "FAILED", "CANCELLED")


class GpWriteOutbox(Base):
    """One GP write that was accepted from a user but could not reach GP yet.

    Today `relay_call` raises the moment the socket is gone, so a backend deploy turns an in-progress
    receive into a red toast that a human has to notice and re-click. That is the failure this table
    removes: the write is accepted, queued, and drained automatically when the relay reconnects.

    **The row carries the whole remainder of the pipeline as data.** Both GP-first resolvers persist
    the UC Nexus record only AFTER the relay answers - `_persist_create_receive` needs the relay
    result, and `_persist_register_po` stamps GP's returned PO number - so deferring the relay call
    means deferring the persist too. `payload` is exactly what `_prepare_*` built (it runs at enqueue
    time, so validation still fails fast in front of the user), and `persist_context` holds the
    JSON-safe kwargs the matching `_persist_*` helper takes. The worker rehydrates that blob and calls
    the SAME helper the online path calls, so there is no second persist implementation to drift.

    Ordering is global age order with per-`entity_key` FIFO enforced in the claim query: `entity_key`
    is `po:<uuid>` for both ops, so a receipt can never overtake the registration of the PO it is
    against.

    `idempotency_key` is UNIQUE and ties back to `gp_write_idempotency.key`, so re-submitting the
    same user action while it is queued returns the existing row rather than queueing it twice."""

    __tablename__ = "gp_write_outbox"
    # The index the worker's claim query rides. Declared here (rather than `index=True` on `status`)
    # so `alembic check` sees the same composite index migration 068 creates - the two must agree, or
    # CI's migration-integrity job fails on a model/schema drift that would otherwise go unnoticed.
    __table_args__ = (Index("ix_gp_write_outbox_claim", "status", "next_attempt_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    idempotency_key: Mapped[str] = mapped_column(String, nullable=False, unique=True)
    # The resolver-level op, matching gp_write_idempotency.op: register_po_in_gp | create_receive.
    op: Mapped[str] = mapped_column(String, nullable=False)
    # The relay-level op the payload is for: create_po | create_receipt.
    relay_op: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str] = mapped_column(String, nullable=False)
    payload: Mapped[dict] = mapped_column(JSON, nullable=False)
    persist_context: Mapped[dict] = mapped_column(JSON, nullable=False)
    # FIFO scope. `po:<uuid>` for both ops - see the class docstring.
    entity_key: Mapped[str] = mapped_column(String, nullable=False, index=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    # Human line for the queue UI, e.g. "Receive against PO 0000123".
    label: Mapped[str] = mapped_column(String, nullable=False)
    requested_by: Mapped[str | None] = mapped_column(String, nullable=True)  # Clerk user id

    # String + CHECK rather than a PG enum (precedent: migration 065): a CHECK is trivially
    # reversible and this list will grow. Indexed by the composite claim index below, not on its own -
    # every read of this column is together with next_attempt_at.
    status: Mapped[str] = mapped_column(String, nullable=False, default="PENDING")
    attempts: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    next_attempt_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_error_code: Mapped[str | None] = mapped_column(String, nullable=True)
    failure_kind: Mapped[str | None] = mapped_column(String, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
    succeeded_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
