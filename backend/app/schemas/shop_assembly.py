"""Shop assembly queries + mutations."""

import uuid

import strawberry

from app.database import SessionLocal
from app.repositories import shop_assembly_repository
from app.repositories import warehouse as warehouse_repository

from .converters import opening_item_to_type, shop_assembly_opening_to_type
from .inputs import AssignOpeningsInput, CompleteOpeningInput
from .types import OpeningItem, ShopAssemblyOpening


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
    def my_work(self, assigned_to: str) -> list[ShopAssemblyOpening]:
        with SessionLocal() as session:
            saos = shop_assembly_repository.get_my_work(session, assigned_to)
            return [shop_assembly_opening_to_type(sao) for sao in saos]


@strawberry.type
class ShopAssemblyMutations:
    @strawberry.mutation
    def assign_openings(self, input: AssignOpeningsInput) -> list[ShopAssemblyOpening]:
        opening_ids = [uuid.UUID(str(oid)) for oid in input.opening_ids]
        with SessionLocal() as session:
            result = shop_assembly_repository.assign_openings(session, opening_ids, input.assigned_to)
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
