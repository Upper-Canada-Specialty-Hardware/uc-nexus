"""Shop assembly queries + mutations."""

import uuid

import strawberry
from sqlalchemy import select
from strawberry.types.nodes import FragmentSpread, InlineFragment, SelectedField

from app.auth import current_user, resolve_display_name, tenant_scope
from app.database import SessionLocal
from app.errors import InventoryShortfallError
from app.models.project import Project
from app.repositories import shop_assembly_repository, tenancy
from app.services import notification_service

from .converters import shop_assembly_allocation_review_to_type, shop_assembly_request_to_type
from .enums import ShopAssemblyRequestStatus
from .inputs import CreateShopAssemblyBatchInput
from .types import ShopAssemblyAllocationReview, ShopAssemblyRequest

# The request's own columns plus its stage: what a read may ask for and still take the light path
# (#1856). Everything else on the type hangs off a relationship or a further query.
_LIGHT_FIELDS = frozenset(
    {
        "__typename",
        "id",
        "requestNumber",
        "projectId",
        "status",
        "createdBy",
        "approvedBy",
        "rejectedBy",
        "rejectionReason",
        "createdAt",
        "approvedAt",
        "rejectedAt",
        "integrityNote",
        "stage",
    }
)


def _selected_names(selections) -> set[str]:
    names: set[str] = set()
    for selection in selections:
        if isinstance(selection, SelectedField):
            names.add(selection.name)
        elif isinstance(selection, (FragmentSpread, InlineFragment)):
            names |= _selected_names(selection.selections)
    return names


def _asks_only_for_light_fields(info: strawberry.Info) -> bool:
    """Whether this read selected nothing past the request's own columns and its stage (#1856).

    The landing gauge asks for `{ id stage }` and nothing else, and was paying for every request's
    lines, openings, batches and batch items to be loaded and converted, and its return note worked
    out, to render a count. The GraphQL contract is unchanged: a read that asks for more gets it all.
    """
    return all(_selected_names(field.selections) <= _LIGHT_FIELDS for field in info.selected_fields)


def _requests_to_types(session, reqs, *, include_lines: bool = True) -> list[ShopAssemblyRequest]:
    """Requests with their derived stage, return note, per-batch pull status and GP job, in THREE
    extra queries for the whole list however long it is.

    All three are resolved here rather than as field resolvers: a per-row lookup over Railway's
    network hop is the N+1 this codebase keeps paying for (CLAUDE.md perf rules).

    include_lines=False is the light path (#1856), for requests read without their lines: the stage
    alone, in one extra query, and no return note or GP job, which the light fields do not include.
    """
    pull_statuses = shop_assembly_repository.get_pull_statuses(session, reqs)
    # Passed in, so the stage reads the statuses just read rather than reading them again (#1856).
    stages = shop_assembly_repository.get_request_stages(session, reqs, pull_statuses)
    if not include_lines:
        return [shop_assembly_request_to_type(r, stage=stages.get(r.id), include_lines=False) for r in reqs]
    notes = shop_assembly_repository.get_return_notes(session, reqs)
    projects = {p.id: p for p in session.scalars(select(Project).where(Project.id.in_({r.project_id for r in reqs})))}
    return [
        shop_assembly_request_to_type(
            r,
            stage=stages.get(r.id),
            return_note=notes.get(r.id),
            pull_status_by_id=pull_statuses,
            project=projects.get(r.project_id),
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
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            light = _asks_only_for_light_fields(info)
            reqs = shop_assembly_repository.get_shop_assembly_requests(
                session, pid, status, reopenable_only, company=scope, include_lines=not light
            )
            return _requests_to_types(session, reqs, include_lines=not light)

    @strawberry.field
    def shop_assembly_request(self, info: strawberry.Info, id: strawberry.ID) -> ShopAssemblyRequest:
        """One request with its openings and batches. NOT_FOUND if it does not exist, or belongs to
        another company (#1113), like every other by-id read."""
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            tenancy.require_shop_assembly_request_in_scope(session, request_id, tenant_scope(info))
            req = shop_assembly_repository.get_shop_assembly_request(session, request_id)
            return _requests_to_types(session, [req])[0]

    @strawberry.field
    def shop_assembly_allocation_review(
        self, info: strawberry.Info, request_id: strawberry.ID
    ) -> ShopAssemblyAllocationReview:
        """What the Shop Assembly Manager needs to compose a batch (#643): the request's still-pending
        openings, each opening's owed lines, and the reservation-aware free stock behind them.

        Read-only and open to any signed-in user - it is the same availability arithmetic every other
        screen shows. Creating the batch is what is role-gated. Scoped like the request itself: another
        company's request is NOT_FOUND (#1113).
        """
        rid = uuid.UUID(str(request_id))
        with SessionLocal() as session:
            tenancy.require_shop_assembly_request_in_scope(session, rid, tenant_scope(info))
            review = shop_assembly_repository.get_allocation_review(session, rid)
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
            tenancy.require_shop_assembly_request_in_scope(session, request_id, tenant_scope(info))
            try:
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
            except InventoryShortfallError as e:
                # #1534: purchasing hears of the shortfall too, as on the import path, but only what is not
                # already on order. The refused work rolls back and the notice goes out in a fresh session.
                session.rollback()
                with SessionLocal() as notif_session:
                    if notification_service.notify_gate_shortfall(notif_session, e, net_of_on_order=True) is not None:
                        notif_session.commit()
                raise
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
            tenancy.require_shop_assembly_request_in_scope(session, rid, tenant_scope(info))
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
            tenancy.require_shop_assembly_request_in_scope(session, request_id, tenant_scope(info))
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
            tenancy.require_shop_assembly_batch_in_scope(session, uuid.UUID(str(batch_id)), tenant_scope(info))
            request = shop_assembly_repository.discard_shop_assembly_batch(session, uuid.UUID(str(batch_id)))
            request_id = request.id
            session.commit()
            reqs = [shop_assembly_repository.get_shop_assembly_request(session, request_id)]
            return _requests_to_types(session, reqs)[0]
