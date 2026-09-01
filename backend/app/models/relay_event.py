"""A durable record of every relay connection-slot transition (successor to issue #384)."""

import uuid
from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class RelayEvent(Base):
    """One thing that happened to the relay's single connection slot: a connect, a disconnect, a
    refusal, an adoption. See RelayEventKind for what each one means.

    Deliberately NOT a state table. Nothing reads the newest row to decide whether a relay is up -
    relayStatus answers that from the gateway's in-memory state, which is the only place that can be
    right. These rows exist to answer questions ABOUT that history after the fact, which the Railway
    log cannot: it retains days, and a refused connection is otherwise invisible the moment it scrolls
    away.

    `install_id` is nullable and SET NULL on delete, with `install_label` carrying a snapshot of the
    name beside it. Retiring a workstation must not erase its history, and the history is worth
    nothing if it can only say "some install that no longer exists"."""

    __tablename__ = "relay_events"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Indexed because every read of this table is "the newest N", and the pruner's cutoff rides it too.
    at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow, index=True)
    # A RelayEventKind value. String + CHECK rather than a PG enum, the precedent gp_write_outbox.status
    # set: a CHECK is trivially reversible and this list will grow.
    kind: Mapped[str] = mapped_column(String, nullable=False)
    install_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("relay_installs.id", ondelete="SET NULL"), nullable=True
    )
    install_label: Mapped[str | None] = mapped_column(String, nullable=True)
    # The relay build tag from its hello frame, when it sent one (issue #315).
    build: Mapped[str | None] = mapped_column(String, nullable=True)
    companies: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    # Why, in the words of whichever path decided it - the #384 disconnect reason for a DISCONNECTED
    # row, and the refusal's cause for the REFUSED_* ones.
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Anything else worth keeping that is not worth a column: who held the slot on a REFUSED_SLOT, who
    # armed the window on an ADOPTED.
    detail: Mapped[dict | None] = mapped_column(JSON, nullable=True)
