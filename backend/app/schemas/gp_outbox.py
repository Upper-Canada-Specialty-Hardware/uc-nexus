"""Read + admin surface for the GP write queue (#353 PR E).

Composed into the root Query/Mutation via schemas/queries.py and schemas/mutations.py, never added
to the root types directly (see CLAUDE.md)."""

import uuid

import strawberry

from app.database import SessionLocal
from app.errors import NotFoundError
from app.repositories import gp_outbox_repository

from .converters import gp_outbox_entry_to_type, gp_outbox_summary_to_type
from .enums import GpOutboxStatus
from .types import GpOutboxEntry, GpOutboxSummary


@strawberry.type
class GpOutboxQueries:
    @strawberry.field
    def gp_outbox_summary(self, info: strawberry.Info) -> GpOutboxSummary:
        """Counts behind the queue chip, polled by every open browser - scalar aggregates only."""
        with SessionLocal() as session:
            return gp_outbox_summary_to_type(gp_outbox_repository.summary(session))

    @strawberry.field
    def gp_outbox(
        self, info: strawberry.Info, status: GpOutboxStatus | None = None, limit: int = 100
    ) -> list[GpOutboxEntry]:
        """The queue itself. Readable by any signed-in user because the PO and receiving lists join
        pending entries onto their rows client-side; only retry/cancel are admin-gated."""
        with SessionLocal() as session:
            rows = gp_outbox_repository.list_entries(
                session, status=status.value if status else None, limit=max(1, min(limit, 500))
            )
            return [gp_outbox_entry_to_type(r) for r in rows]


@strawberry.type
class GpOutboxMutations:
    @strawberry.mutation
    def retry_gp_outbox_entry(self, info: strawberry.Info, id: strawberry.ID) -> GpOutboxEntry:
        """Admin: put a failed write back on the queue with a fresh attempt budget.

        For `failureKind == 'ambiguous'` this is a genuinely dangerous button - GP may already hold
        the write - which is why the UI's confirm text says to check GP first. The backend cannot
        know, so it does not pretend to."""
        with SessionLocal() as session:
            row = gp_outbox_repository.retry_entry(session, uuid.UUID(str(id)))
            if row is None:
                raise NotFoundError("No retryable GP write queue entry with that id")
            entry = gp_outbox_entry_to_type(row)
            session.commit()
        # Drain immediately rather than waiting for the next poll tick.
        from app.services import gp_outbox_worker

        gp_outbox_worker.wake()
        return entry

    @strawberry.mutation
    def cancel_gp_outbox_entry(self, info: strawberry.Info, id: strawberry.ID) -> GpOutboxEntry:
        """Admin: abandon a queued write. Refused for an IN_FLIGHT row - cancelling one would leave
        the worker still writing to a row a human believes is dead."""
        with SessionLocal() as session:
            row = gp_outbox_repository.cancel_entry(session, uuid.UUID(str(id)))
            if row is None:
                raise NotFoundError("No cancellable GP write queue entry with that id")
            entry = gp_outbox_entry_to_type(row)
            session.commit()
            return entry
