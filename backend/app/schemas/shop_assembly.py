"""Shop assembly queries + mutations."""

import uuid

import strawberry

from app.auth import SHOP_ASSEMBLY_MANAGER_ROLE, require_role, require_user
from app.database import SessionLocal
from app.repositories import shop_assembly_repository, user_repository
from app.repositories import warehouse as warehouse_repository

from .converters import (
    assembly_pipeline_summary_to_type,
    assembly_pipeline_to_type,
    clerk_user_to_type,
    opening_item_to_type,
    replacement_work_item_to_type,
    shop_assembly_opening_to_type,
    shop_assembly_request_to_type,
)
from .enums import ShopAssemblyRequestStatus
from .inputs import (
    AssignOpeningsInput,
    CompleteOpeningInput,
    InstallReplacementInput,
    RecordAssemblyProgressInput,
)
from .types import (
    AssemblyPipeline,
    AssemblyPipelineSummary,
    ClerkUser,
    OpeningItem,
    ReplacementWorkItem,
    ShopAssemblyOpening,
    ShopAssemblyRequest,
)


@strawberry.type
class ShopAssemblyQueries:
    @strawberry.field
    def assemble_list(
        self, info: strawberry.Info, project_id: strawberry.ID | None = None
    ) -> list[ShopAssemblyOpening]:
        """Openings whose shop-assembly pull is complete (#222). Open to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            saos = shop_assembly_repository.get_assemble_list(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.field
    def my_work(self, info: strawberry.Info, assigned_to_user_id: str) -> list[ShopAssemblyOpening]:
        """An assembler's claimed, unfinished openings - PENDING or IN_PROGRESS (#340), so a leaf with
        saved partial progress stays reachable. Open to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            saos = shop_assembly_repository.get_my_work(session, assigned_to_user_id)
            return [shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.field
    def replacement_work(
        self,
        info: strawberry.Info,
        assigned_to_user_id: str | None = None,
        project_id: strawberry.ID | None = None,
    ) -> list[ReplacementWorkItem]:
        """Replacement installs outstanding on already-completed leaves (#341).

        Scoped to one assembler by assignedToUserId, which is what puts the work in the My Work board
        of whoever last held the leaf - the ShopAssemblyOpening keeps its assignment through
        completion, so no new assignment concept is needed. Rows whose leaf has already shipped are
        included deliberately: that replacement must stay visible rather than be stranded, and the
        caller can tell from openingItemState that it needs reallocation instead of an install. Open
        to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            rows = shop_assembly_repository.get_replacement_work(
                session,
                assigned_to_user_id=assigned_to_user_id,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
            )
            return [replacement_work_item_to_type(r) for r in rows]

    @strawberry.field
    def shop_assembly_requests(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        status: ShopAssemblyRequestStatus | None = None,
        reopenable_only: bool = False,
    ) -> list[ShopAssemblyRequest]:
        """Accept UI (#293): shop-assembly requests for a project, PENDING by default. reopenableOnly
        (#325) keeps only requests whose minted pull request is still PENDING - the Approved/reopen
        view uses it so it lists only requests Reopen can still act on. Open to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            reqs = shop_assembly_repository.get_shop_assembly_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, status, reopenable_only
            )
            return [shop_assembly_request_to_type(r) for r in reqs]

    @strawberry.field
    def assembly_pipeline_summaries(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        status: ShopAssemblyRequestStatus | None = None,
    ) -> list[AssemblyPipelineSummary]:
        """Where every shop-assembly request has got to (#344), newest first.

        One row per request, carrying the whole ladder as counts: requested -> accepted -> staged x/y
        (or cancelled) -> assigned -> in progress n/m units -> completed -> shipped, plus the three
        flags earlier slices introduced (the #342 integrity note, units awaiting replacement, and
        replacements that arrived after their leaf shipped).

        Omit projectId for the All-Projects view. That is safe here by construction: the repository
        runs a fixed five statements - the requests, their pulls, and three grouped aggregates -
        however many requests come back, so the cost of this resolver grows with rows returned and
        not with queries issued. Open to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            rows = shop_assembly_repository.get_assembly_pipeline_summaries(
                session,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
                status=status,
            )
            return [assembly_pipeline_summary_to_type(r) for r in rows]

    @strawberry.field
    def assembly_pipeline(self, info: strawberry.Info, request_id: strawberry.ID) -> AssemblyPipeline:
        """One request's pipeline, down to the individual door leaf (#344).

        This is the view that answers "where is opening A01 leaf 2?" in one place instead of four:
        each leaf's rung on the ladder, who is holding it, how many of its units are fitted, where
        the assembled unit was put away, and what it is still owed. The header counts come from the
        same aggregates the list uses, so this screen and that one cannot disagree.

        Open to any signed-in user."""
        require_user(info)
        with SessionLocal() as session:
            pipeline = shop_assembly_repository.get_assembly_pipeline(session, uuid.UUID(str(request_id)))
            return assembly_pipeline_to_type(pipeline)

    @strawberry.field
    def shop_assembly_members(self, info: strawberry.Info) -> list[ClerkUser]:
        """Shop-assembly team members for the manager assignment picker (#330). Manager-gated: only
        a Shop Assembly Manager may enumerate members and assign pulled openings to them."""
        require_role(info, SHOP_ASSEMBLY_MANAGER_ROLE)
        return [clerk_user_to_type(u) for u in user_repository.list_shop_assembly_members()]


@strawberry.type
class ShopAssemblyMutations:
    @strawberry.mutation
    def accept_shop_assembly_request(
        self, info: strawberry.Info, id: strawberry.ID, accepted_by: str
    ) -> ShopAssemblyRequest:
        """Accept a PENDING shop-assembly request (#293). Open to any signed-in user.

        A pure human approval gate since #342: it mints the warehouse PullRequest and approves the
        request, and re-checks nothing. The hardware was reserved when the request was created, so
        it already belongs to this request - there is no shortfall left for the acceptor to be shown
        and nothing they could do about one if there were."""
        require_user(info)
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.accept_shop_assembly_request(session, request_id, accepted_by)
            session.commit()
            refreshed = shop_assembly_repository.get_request_with_openings(session, request_id)
            return shop_assembly_request_to_type(refreshed)

    @strawberry.mutation
    def reject_shop_assembly_request(
        self, info: strawberry.Info, id: strawberry.ID, rejected_by: str, reason: str | None = None
    ) -> ShopAssemblyRequest:
        """Reject a PENDING shop-assembly request (#293). Open to any signed-in user."""
        require_user(info)
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.reject_shop_assembly_request(session, request_id, rejected_by, reason)
            session.commit()
            refreshed = shop_assembly_repository.get_request_with_openings(session, request_id)
            return shop_assembly_request_to_type(refreshed)

    @strawberry.mutation
    def reopen_shop_assembly_request(self, info: strawberry.Info, id: strawberry.ID) -> ShopAssemblyRequest:
        """Reopen an APPROVED shop-assembly request back to PENDING (#325). Undoes an erroneous accept:
        hard-deletes the warehouse PullRequest the accept minted, re-points the request's openings off
        it, and flips the request to PENDING so it can be re-accepted or rejected. Refused if the
        warehouse has already worked the pull. Open to any signed-in user."""
        require_user(info)
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            shop_assembly_repository.reopen_shop_assembly_request(session, request_id)
            session.commit()
            refreshed = shop_assembly_repository.get_request_with_openings(session, request_id)
            return shop_assembly_request_to_type(refreshed)

    @strawberry.mutation
    def assign_openings(self, info: strawberry.Info, input: AssignOpeningsInput) -> list[ShopAssemblyOpening]:
        """Assign pulled openings to a user (#330). Any signed-in user may self-assign (the "Assign to
        me" board); assigning to *another* user is Shop Assembly Manager-gated, so the manager-only
        guarantee holds at the data layer, not just the UI.

        Reassignment (#340) rides on that same distinction. Progress is persisted per item now, so
        handing a half-built leaf to someone else loses nothing - but only the manager branch may take
        an opening off whoever is holding it, so allow_reassign is passed exactly when the caller has
        already been through require_role. A self-claim can never steal: it takes the is_self branch,
        which passes allow_reassign=False, and the repository refuses on a conflicting holder. That
        also means a manager claiming work *for themselves* must unassign it first - the safer read of
        an ambiguous action, and one keystroke, not a hole.
        """
        auth = require_user(info)
        is_self = input.assigned_to_user_id == auth["user_id"]
        if not is_self:
            require_role(info, SHOP_ASSEMBLY_MANAGER_ROLE)
        opening_ids = [uuid.UUID(str(oid)) for oid in input.opening_ids]
        with SessionLocal() as session:
            result = shop_assembly_repository.assign_openings(
                session,
                opening_ids,
                input.assigned_to_user_id,
                input.assigned_to,
                allow_reassign=not is_self,
            )
            session.commit()
            saos = shop_assembly_repository.get_openings_with_items(session, [o.id for o in result])
            return [shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.mutation
    def remove_opening_from_user(self, info: strawberry.Info, opening_id: strawberry.ID) -> ShopAssemblyOpening:
        """Unassign an unfinished opening. Allowed while it is PENDING or IN_PROGRESS (#340) - saved
        progress lives on the item rows, so returning a half-built leaf to the pool loses nothing.
        Open to any signed-in user (the board's Unassign action)."""
        require_user(info)
        with SessionLocal() as session:
            result = shop_assembly_repository.remove_opening_from_user(session, uuid.UUID(str(opening_id)))
            session.commit()
            refreshed = shop_assembly_repository.get_openings_with_items(session, [result.id])[0]
            return shop_assembly_opening_to_type(refreshed)

    @strawberry.mutation
    def record_assembly_progress(
        self, info: strawberry.Info, input: RecordAssemblyProgressInput
    ) -> ShopAssemblyOpening:
        """Save what an assembler has fitted to a leaf so far (#340), without finishing it.

        This is what makes assembly resumable: the counts land on the ShopAssemblyOpeningItem rows,
        the opening flips to IN_PROGRESS on the first save and stays in the assembler's My Work, and
        any units flagged deficient are returned to inventory and given a replacement pull line
        immediately rather than waiting for completion. Open to any signed-in user - it moves
        inventory when a deficiency is flagged, so it must not be reachable anonymously."""
        require_user(info)
        updates = [
            shop_assembly_repository.AssemblyProgressUpdate(
                shop_assembly_opening_item_id=uuid.UUID(str(item.shop_assembly_opening_item_id)),
                installed_quantity=item.installed_quantity,
                flag_deficient_quantity=item.flag_deficient_quantity,
                deficient_reason=item.deficient_reason,
            )
            for item in input.items
        ]
        with SessionLocal() as session:
            result = shop_assembly_repository.record_assembly_progress(
                session,
                uuid.UUID(str(input.opening_id)),
                updates,
                performed_by=input.performed_by,
            )
            session.commit()
            refreshed = shop_assembly_repository.get_openings_with_items(session, [result.id])[0]
            return shop_assembly_opening_to_type(refreshed)

    @strawberry.mutation
    def install_replacement(self, info: strawberry.Info, input: InstallReplacementInput) -> OpeningItem:
        """Fit arrived replacement hardware to an already-completed door leaf (#341).

        The one legitimate write to an assembled leaf's hardware after completion: it appends or
        increments the leaf's OpeningItemHardware row for that product and moves the units from
        replacement_pending to installed on the source checklist line, so the completion invariant
        holds throughout. It can only spend units the replacement pull actually delivered, and it
        refuses a leaf that has already shipped. Open to any signed-in user - it changes what an
        assembled leaf is recorded as carrying, so it must not be reachable anonymously."""
        require_user(info)
        with SessionLocal() as session:
            result = shop_assembly_repository.install_replacement(
                session,
                uuid.UUID(str(input.shop_assembly_opening_item_id)),
                input.quantity,
                performed_by=input.performed_by,
            )
            session.commit()
            refreshed = warehouse_repository.get_opening_item_details(session, result.id)
            shortfall = shop_assembly_repository.get_leaf_shortfalls(session, [refreshed.id]).get(refreshed.id)
            return opening_item_to_type(
                refreshed,
                awaiting_replacement_quantity=shortfall.awaiting_replacement if shortfall else 0,
                never_pulled_quantity=shortfall.never_pulled if shortfall else 0,
            )

    @strawberry.mutation
    def complete_opening(self, info: strawberry.Info, input: CompleteOpeningInput) -> OpeningItem:
        """Complete an opening's assembly, materializing the assembled leaf as an OpeningItem (#339).

        Takes no checklist (#340): completion reads the per-item counts recordAssemblyProgress has
        been persisting, and is refused while any unit is still unaccounted for. Open to any signed-in
        user - it writes inventory, so it must not be reachable anonymously."""
        require_user(info)
        with SessionLocal() as session:
            result = shop_assembly_repository.complete_opening(
                session,
                uuid.UUID(str(input.opening_id)),
                input.aisle,
                input.row,
                input.bay,
                completed_by=input.completed_by,
            )
            session.commit()
            # Re-load with installed_hardware
            refreshed = warehouse_repository.get_opening_item_details(session, result.id)
            return opening_item_to_type(refreshed)
