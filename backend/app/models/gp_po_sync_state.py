"""Per-company cursor for the GP purchase-order mirror sync (gp-owned-po mirror).

One row per enrolled GP company. The mirror runs in two phases and this row records which one it is
in. During BACKFILL it walks GP's whole PO history in po-number order, advancing `backfill_cursor`
after each drained page; when a page comes back short it flips `backfill_done` true. From then on it
runs INCREMENTAL, re-pulling only rows GP has touched since `watermark` (minus a day's slack, because
GP's modified date is day-granular and a same-day edit after the pass would otherwise be missed).

The row dies with the schema on a dev reset, which needs no special handling: with no state the loop
simply backfills fresh after the project sync has re-adopted the jobs a mirrored PO matches on.
"""

import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class GpPoSyncState(Base):
    __tablename__ = "gp_po_sync_state"
    __table_args__ = (UniqueConstraint("company", name="uq_gp_po_sync_state_company"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # GP company code (TUBC/TUCSH for the POC). One row per company; the enrolled relay's company.
    company: Mapped[str] = mapped_column(String(15), nullable=False)
    # High-water mark for the incremental phase: the newest GP modified-date seen on the last pass.
    # Null until the first pass records one. The incremental read filters MODIFDT >= watermark - 1 day.
    watermark: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Keyset cursor for the backfill phase: the last PONUMBER pulled. Null before the first page.
    backfill_cursor: Mapped[str | None] = mapped_column(String(17), nullable=True)
    # True once a backfill page came back short (history drained). The loop then only runs incremental.
    backfill_done: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
