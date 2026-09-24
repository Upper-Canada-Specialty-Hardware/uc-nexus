"""Read + management surface for the GP write queue (#353 PR E).

Composed into the root Query/Mutation via schemas/queries.py and schemas/mutations.py, never added
to the root types directly (see CLAUDE.md)."""

import uuid

import strawberry

from app.auth import PO_MANAGERS, TENANT_OWNERS, WAREHOUSE_MANAGERS, require_any_role, tenant_scope
from app.database import SessionLocal
from app.errors import NotFoundError
from app.repositories import gp_outbox_repository, user_repository

from .converters import gp_outbox_entry_to_type, gp_outbox_summary_to_type
from .enums import GpOutboxStatus
from .types import GpOutboxEntry, GpOutboxSummary

# Who may retry or cancel a held write, by the GP-side op it is waiting to make (#729). A held write
# belongs to whoever raises that kind of work, because retrying one can duplicate a GP posting and
# cancelling one abandons work somebody has already done - so the decision sits with the people who
# would have to live with either outcome, not with everyone signed in.
#
# Keyed on `relay_op`, the GP-side name that identifies a NEXUS TO GP WRITE. Anything not
# listed - create_job, create_buyer, create_customer_address, update_job_site - is a tenant owner's,
# because those are all sub-steps of Tenant Owner screens.
_ROLES_BY_RELAY_OP: dict[str, frozenset[str]] = {
    # A held PO REGISTRATION is the PO module's, so the people who raise POs as well as the ones who
    # manage the module.
    "create_po": PO_MANAGERS | {user_repository.PO_USER_ROLE},
    # A held GP RECEIVE ENTRY is the warehouse's, at the same bar approving the receive itself sets.
    "create_receipt": WAREHOUSE_MANAGERS,
}


# The one answer for "that entry is not yours" and for "there is no such entry", said the same way
# so the two cannot be told apart from outside.
_NO_RETRYABLE_ENTRY = "No retryable GP write queue entry with that id"
_NO_CANCELLABLE_ENTRY = "No cancellable GP write queue entry with that id"


def _authorize_entry(info: strawberry.Info, entry, absent_message: str) -> None:
    """Refuse a caller who may not act on this held write: wrong company first, then wrong role.

    The company check comes first because it decides whether the entry is any of the caller's
    business at all; the role check then decides whether this kind of write is.

    Out of scope answers NOT FOUND, with the same message the resolver gives for an id that is not
    in the table. That is the rule every by-id check in `app/repositories/tenancy.py` follows, for
    the same reason: a forbidden answer confirms the entry exists, which turns an id-taking field
    into an oracle over another company's write queue.
    """
    scope = tenant_scope(info)
    if scope is not None and user_repository.normalize_company(entry.company) != scope:
        raise NotFoundError(absent_message)
    require_any_role(info, _ROLES_BY_RELAY_OP.get(entry.relay_op, TENANT_OWNERS))


@strawberry.type
class GpOutboxQueries:
    @strawberry.field
    def gp_outbox_summary(self, info: strawberry.Info) -> GpOutboxSummary:
        """Counts behind the queue chip, polled by every open browser - scalar aggregates only.

        Scoped to the caller's own company (#729), like the list beside it: a chip counting another
        tenant's held writes would send somebody looking for work that is not theirs to see."""
        with SessionLocal() as session:
            return gp_outbox_summary_to_type(gp_outbox_repository.summary(session, company=tenant_scope(info)))

    @strawberry.field
    def gp_outbox(
        self,
        info: strawberry.Info,
        status: GpOutboxStatus | None = None,
        limit: int = 100,
        ops: list[str] | None = None,
    ) -> list[GpOutboxEntry]:
        """The queue itself. Readable by any signed-in user because the PO and receiving lists join
        pending entries onto their rows client-side; retry and cancel are decided per entry.

        `ops` narrows it to one kind of GP write, named as the relay op - `create_po`,
        `create_receipt`, `update_job_site`. That is what lets a module show only the held writes it
        owns rather than the whole queue.

        Company-scoped (#729). The row carries the GP company its write is for, so this stays on
        the caller's side of the GP COMPANY NEXUS TENANT line however the field is called; only an
        unscoped UC NEXUS ADMIN sees every company's queue."""
        with SessionLocal() as session:
            rows = gp_outbox_repository.list_entries(
                session,
                status=status.value if status else None,
                limit=max(1, min(limit, 500)),
                ops=ops or None,
                company=tenant_scope(info),
            )
            return [gp_outbox_entry_to_type(r) for r in rows]


@strawberry.type
class GpOutboxMutations:
    @strawberry.mutation
    def retry_gp_outbox_entry(self, info: strawberry.Info, id: strawberry.ID) -> GpOutboxEntry:
        """Put a failed write back on the queue with a fresh attempt budget.

        Who may is decided from the entry rather than from the field (#729) - see
        `_ROLES_BY_RELAY_OP`. For `failureKind == 'ambiguous'` this is a genuinely dangerous button -
        GP may already hold the write - which is why the UI's confirm text says to check GP first.
        The backend cannot know, so it does not pretend to."""
        with SessionLocal() as session:
            entry_row = gp_outbox_repository.get_entry(session, uuid.UUID(str(id)))
            if entry_row is None:
                raise NotFoundError(_NO_RETRYABLE_ENTRY)
            _authorize_entry(info, entry_row, _NO_RETRYABLE_ENTRY)

            row = gp_outbox_repository.retry_entry(session, uuid.UUID(str(id)))
            if row is None:
                raise NotFoundError(_NO_RETRYABLE_ENTRY)
            entry = gp_outbox_entry_to_type(row)
            session.commit()
        # Drain immediately rather than waiting for the next poll tick.
        from app.services import gp_outbox_worker

        gp_outbox_worker.wake()
        return entry

    @strawberry.mutation
    def cancel_gp_outbox_entry(self, info: strawberry.Info, id: strawberry.ID) -> GpOutboxEntry:
        """Abandon a queued write, at the same bar retrying it sets. Refused for an IN_FLIGHT row -
        cancelling one would leave the worker still writing to a row a human believes is dead."""
        with SessionLocal() as session:
            entry_row = gp_outbox_repository.get_entry(session, uuid.UUID(str(id)))
            if entry_row is None:
                raise NotFoundError(_NO_CANCELLABLE_ENTRY)
            _authorize_entry(info, entry_row, _NO_CANCELLABLE_ENTRY)

            row = gp_outbox_repository.cancel_entry(session, uuid.UUID(str(id)))
            if row is None:
                raise NotFoundError(_NO_CANCELLABLE_ENTRY)
            entry = gp_outbox_entry_to_type(row)
            session.commit()
            return entry
