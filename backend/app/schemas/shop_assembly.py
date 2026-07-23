"""Shop assembly queries + mutations."""

import uuid

import strawberry

from app.auth import SHOP_ASSEMBLY_MANAGER_ROLE, require_role, require_user
from app.database import SessionLocal
from app.errors import InventoryShortfallError
from app.repositories import shop_assembly_repository, user_repository
from app.repositories import warehouse as warehouse_repository
from app.services import notification_service

from .converters import (
    clerk_user_to_type,
    opening_item_to_type,
    shop_assembly_opening_to_type,
    shop_assembly_request_to_type,
)
from .enums import ShopAssemblyRequestStatus
from .inputs import AssignOpeningsInput, CompleteOpeningInput
from .types import ClerkUser, OpeningItem, ShopAssemblyOpening, ShopAssemblyRequest


@strawberry.type
class ShopAssemblyQueries:
    @strawberry.field
    def assemble_list(self, project_id: strawberry.ID | None = None) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            saos = shop_assembly_repository.get_assemble_list(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.field
    def my_work(self, assigned_to_user_id: str) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            saos = shop_assembly_repository.get_my_work(session, assigned_to_user_id)
            return [shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.field
    def shop_assembly_requests(
        self,
        project_id: strawberry.ID | None = None,
        status: ShopAssemblyRequestStatus | None = None,
    ) -> list[ShopAssemblyRequest]:
        """Accept UI (#293): shop-assembly requests for a project, PENDING by default."""
        with SessionLocal() as session:
            reqs = shop_assembly_repository.get_shop_assembly_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, status
            )
            return [shop_assembly_request_to_type(r) for r in reqs]

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
        """Accept a PENDING shop-assembly request (#293). Open to any signed-in user. Re-checks
        inventory sufficiency; if short, notifies the PO for backfill and raises the shortfall inline
        without minting the PR. If covered, mints the warehouse PullRequest and approves the request."""
        require_user(info)
        request_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            try:
                shop_assembly_repository.accept_shop_assembly_request(session, request_id, accepted_by)
                session.commit()
            except InventoryShortfallError as e:
                # Roll the mint back so no PR/partial state survives, then notify the PO for backfill
                # in a fresh session so it outlives the rollback, and re-raise so the shortfall
                # reaches the caller inline.
                session.rollback()
                with SessionLocal() as notif_session:
                    notification_service.notify_po_shortfall(
                        notif_session,
                        project_id=e.project_id,
                        request_number=e.request_number,
                        shortfalls=e.shortfalls,
                    )
                    notif_session.commit()
                raise
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
    def assign_openings(self, input: AssignOpeningsInput) -> list[ShopAssemblyOpening]:
        opening_ids = [uuid.UUID(str(oid)) for oid in input.opening_ids]
        with SessionLocal() as session:
            result = shop_assembly_repository.assign_openings(
                session, opening_ids, input.assigned_to_user_id, input.assigned_to
            )
            session.commit()
            saos = shop_assembly_repository.get_openings_with_items(session, [o.id for o in result])
            return [shop_assembly_opening_to_type(sao) for sao in saos]

    @strawberry.mutation
    def remove_opening_from_user(self, opening_id: strawberry.ID) -> ShopAssemblyOpening:
        with SessionLocal() as session:
            result = shop_assembly_repository.remove_opening_from_user(session, uuid.UUID(str(opening_id)))
            session.commit()
            refreshed = shop_assembly_repository.get_openings_with_items(session, [result.id])[0]
            return shop_assembly_opening_to_type(refreshed)

    @strawberry.mutation
    def complete_opening(self, input: CompleteOpeningInput) -> OpeningItem:
        with SessionLocal() as session:
            item_results = [
                shop_assembly_repository.OpeningItemResult(
                    shop_assembly_opening_item_id=uuid.UUID(str(r.shop_assembly_opening_item_id)),
                    installed=r.installed,
                    deficient_reason=r.deficient_reason,
                )
                for r in input.item_results
            ]
            result = shop_assembly_repository.complete_opening(
                session,
                uuid.UUID(str(input.opening_id)),
                input.aisle,
                input.row,
                input.bay,
                item_results=item_results,
                completed_by=input.completed_by,
            )
            session.commit()
            # Re-load with installed_hardware
            refreshed = warehouse_repository.get_opening_item_details(session, result.id)
            return opening_item_to_type(refreshed)
