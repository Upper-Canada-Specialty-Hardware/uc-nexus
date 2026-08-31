"""Shop assembly queries + mutations."""

import uuid

import strawberry

from app.auth import current_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import shop_assembly_repository

from .converters import shop_assembly_allocation_review_to_type, shop_assembly_request_to_type
from .enums import ShopAssemblyRequestStatus
from .inputs import CreateShopAssemblyBatchInput
from .types import ShopAssemblyAllocationReview, ShopAssemblyRequest


def _requests_to_types(session, reqs) -> list[ShopAssemblyRequest]:
    """Requests with their derived stage, return note and per-batch pull status, in THREE extra
    queries for the whole list however long it is.

    All three are resolved here rather than as field resolvers: a per-row lookup over Railway's
    network hop is the N+1 this codebase keeps paying for (CLAUDE.md perf rules).
    """
    pull_statuses = shop_assembly_repository.get_pull_statuses(session, reqs)
    stages = shop_assembly_repository.get_request_stages(session, reqs)
    notes = shop_assembly_repository.get_return_notes(session, reqs)
    return [
        shop_assembly_request_to_type(
            r,
            stage=stages.get(r.id),
            return_note=notes.get(r.id),
            pull_status_by_id=pull_statuses,
        )
        for r in reqs
    ]


@strawberry.type
class ShopAssemblyQueries:
    @strawberry.field
    def shop_assembly_requests(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        status: ShopAssemblyRequestStatus | None = None,
        reopenable_only: bool = False,
    ) -> list[ShopAssemblyRequest]:
        """Shop-assembly requests for a project, PENDING by default.

        reopenableOnly keeps only requests carrying a batch whose pull is still PENDING - the
        Accepted view uses it so it lists only requests a discard can still act on. Open to any
        signed-in user.
        """
        with SessionLocal() as session:
            reqs = shop_assembly_repository.get_shop_assembly_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, status, reopenable_only
            )
            return _requests_to_types(session, reqs)

    @strawberry.field
    def shop_assembly_request(self, info: strawberry.Info, id: strawberry.ID) -> ShopAssemblyRequest:
        """One request with its openings and batches. NOT_FOUND if it does not exist."""
        with SessionLocal() as session:
            req = shop_assembly_repository.get_shop_assembly_request(session, uuid.UUID(str(id)))
            return _requests_to_types(session, [req])[0]

    @strawberry.field
    def shop_assembly_allocation_review(
        self, info: strawberry.Info, request_id: strawberry.ID
    ) -> ShopAssemblyAllocationReview:
        """What the Shop Assembly Manager needs to compose a batch (#643): the request's still-pending
        openings, each opening's owed lines, and the reservation-aware free stock behind them.

        Read-only and open to any signed-in user - it is the same availability arithmetic every other
        screen shows. Creating the batch is what is role-gated.
        """
        with SessionLocal() as session:
            review = shop_assembly_repository.get_allocation_review(session, uuid.UUID(str(request_id)))
            return shop_assembly_allocation_review_to_type(review)


@strawberry.type
class ShopAssemblyMutations:
    @strawberry.mutation
    def create_shop_assembly_batch(
        self, info: strawberry.Info, input: CreateShopAssemblyBatchInput
    ) -> ShopAssemblyRequest:
        """Dispatch a subset of a pending request's openings at the quantities the manager allocated
        (#646). This is what the accept gate became.

        It gates on available inventory for exactly these allocations, reserves them, and mints the
        warehouse PullRequest. Partial is fine - a batch may take less than an opening is owed - but
        batching an opening CONSUMES it: the remainder is forfeited, because the batch is the
        decision for that opening.

        Recorded against the Clerk-authenticated caller (#427), whose name also becomes the minted
        pull's `requestedBy`. Role-gated in ROOT_FIELD_POLICY: this one commits real inventory.
        """
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(input.request_id))
        with SessionLocal() as session:
            shop_assembly_repository.create_shop_assembly_batch(
                session,
                request_id,
                [
                    {
                        "opening_number": line.opening_number,
                        "hardware_category": line.hardware_category,
                        "product_code": line.product_code,
                        "allocated_quantity": line.allocated_quantity,
                    }
                    for line in input.lines
                ],
                created_by=actor,
            )
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]

    @strawberry.mutation
    def dismiss_shop_assembly_openings(
        self,
        info: strawberry.Info,
        request_id: strawberry.ID,
        opening_numbers: list[str] | None = None,
        reason: str | None = None,
    ) -> ShopAssemblyRequest:
        """Write off pending openings the manager is not going to batch (#646).

        Omit `openingNumbers` to dismiss every opening still pending, which is how a request that has
        had what it is going to get is finished off. Releases nothing - a pending opening never held
        a claim. Recorded against the Clerk-authenticated caller.
        """
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        rid = uuid.UUID(str(request_id))
        with SessionLocal() as session:
            shop_assembly_repository.dismiss_shop_assembly_openings(
                session, rid, opening_numbers, dismissed_by=actor, reason=reason
            )
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, rid)]
            return _requests_to_types(session, reqs)[0]

    @strawberry.mutation
    def reject_shop_assembly_request(
        self, info: strawberry.Info, id: strawberry.ID, reason: str | None = None
    ) -> ShopAssemblyRequest:
        """Turn a whole shop-assembly request down. Refused once it has been batched (#646) - by then
        part of it has happened, and the honest ways out are cancelling the pull and dismissing the
        rest. Recorded against the Clerk-authenticated caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.reject_shop_assembly_request(session, request_id, actor, reason)
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]

    @strawberry.mutation
    def discard_shop_assembly_batch(self, info: strawberry.Info, batch_id: strawberry.ID) -> ShopAssemblyRequest:
        """Undo a batch the warehouse has not started (#646) - the #325 reopen, at batch granularity.

        Hard-deletes the pull the batch minted, releases the claim it was holding, and hands its
        openings back to Pending. Refused if the warehouse has already started that pull; cancel the
        pull instead. Returns the batch's request."""
        with SessionLocal() as session:
            request = shop_assembly_repository.discard_shop_assembly_batch(session, uuid.UUID(str(batch_id)))
            request_id = request.id
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]
