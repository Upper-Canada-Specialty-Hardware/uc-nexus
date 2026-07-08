from datetime import datetime

from sqlalchemy import JSON, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class GpWriteIdempotency(Base):
    """Idempotency ledger for the GP-first writes (create_po / register_po_in_gp / create_receive).

    Each of those resolvers pushes to GP via the relay BEFORE persisting the UC Nexus record, so the two
    systems are not atomic: a crash or a repo-side failure after the GP write would let a client retry
    post a SECOND GP receipt (double-count) or reserve a duplicate GP PO number. The client generates one
    key per user action and re-sends it on retry; the resolver keys this ledger by it:

    - relay_result recorded (own commit) right after the GP write succeeds -> a retry whose persist
      failed reuses it instead of hitting GP again.
    - result_id stamped in the SAME transaction as the persist -> a retry after full success returns the
      already-created record without re-persisting.

    This closes the frontend-retry double-post the deleted client-side gpReceiptPostedRef guard used to
    cover. The only residual window (crash between the GP write and the relay_result commit) is inherent
    without GP-side idempotency and is far smaller than the pre-fix window."""

    __tablename__ = "gp_write_idempotency"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    op: Mapped[str] = mapped_column(String, nullable=False)
    # the relay's returned result (po_number+company for a PO op; the receipt result for a receive).
    relay_result: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    # the created/updated UC Nexus record id (PO id or receive-record id) as a string, set once the
    # persist commits.
    result_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
