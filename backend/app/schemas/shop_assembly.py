"""Shop assembly queries + mutations."""

import uuid

import strawberry

from app.auth import current_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import shop_assembly_repository

from .converters import shop_assembly_request_to_type
from .enums import ShopAssemblyRequestStatus
from .types import ShopAssemblyRequest


def _requests_to_types(session, reqs) -> list[ShopAssemblyRequest]:
    """Requests with their derived stage, in ONE extra query for the whole list.

    The stage is what the requests page draws as columns, so it is resolved here rather than as a
    field resolver: a per-row lookup over Railway's network hop is the N+1 this codebase keeps
    paying for (CLAUDE.md perf rules).
    """
    stages = shop_assembly_repository.get_request_stages(session, reqs)
    return [shop_assembly_request_to_type(r, stage=stages.get(r.id)) for r in reqs]


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
        """Shop-assembly requests for a project, PENDING by default (#293).

        reopenableOnly (#325) keeps only requests whose minted pull is still PENDING - the Approved
        view uses it so it lists only requests Reopen can still act on. Open to any signed-in user.
        """
        with SessionLocal() as session:
            reqs = shop_assembly_repository.get_shop_assembly_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, status, reopenable_only
            )
            return _requests_to_types(session, reqs)


@strawberry.type
class ShopAssemblyMutations:
    @strawberry.mutation
    def accept_shop_assembly_request(self, info: strawberry.Info, id: strawberry.ID) -> ShopAssemblyRequest:
        """Accept a PENDING shop-assembly request (#293). Open to any signed-in user.

        A pure human approval gate since #342: it mints the warehouse PullRequest and approves the
        request, and re-checks nothing. The hardware was reserved when the request was created, so
        it already belongs to this request - there is no shortfall left for the acceptor to be shown
        and nothing they could do about one if there were.

        The approval is recorded against the Clerk-authenticated caller (#427). It is the whole
        content of the gate: an approval attributable to anyone the client names is not an approval.
        The name also becomes the minted pull's `requestedBy`."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.accept_shop_assembly_request(session, request_id, actor)
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]

    @strawberry.mutation
    def reject_shop_assembly_request(
        self, info: strawberry.Info, id: strawberry.ID, reason: str | None = None
    ) -> ShopAssemblyRequest:
        """Reject a PENDING shop-assembly request (#293). Open to any signed-in user. Recorded
        against the Clerk-authenticated caller (#427), same reasoning as the accept."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.reject_shop_assembly_request(session, request_id, actor, reason)
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]

    @strawberry.mutation
    def reopen_shop_assembly_request(self, info: strawberry.Info, id: strawberry.ID) -> ShopAssemblyRequest:
        """Reopen an APPROVED shop-assembly request back to PENDING (#325).

        Undoes an erroneous accept: hard-deletes the warehouse PullRequest the accept minted and
        flips the request to PENDING so it can be re-accepted or rejected. Refused if the warehouse
        has already started the pull. Open to any signed-in user."""
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.reopen_shop_assembly_request(session, request_id)
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]
