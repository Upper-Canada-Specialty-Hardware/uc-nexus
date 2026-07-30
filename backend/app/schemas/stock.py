"""Stock pool + deficiency queries and mutations.

Every mutation here writes an audit row, and since #427 the actor on it is the Clerk-authenticated
caller (`current_user` -> `resolve_display_name`), never the request's own `performedBy`/`reviewedBy`
field. Those input fields survived #427 as ignored no-ops so a frontend from the previous deploy kept
validating, and came out of the schema entirely in #438. Before the change these rows carried
whatever the client sent, defaulting to the literal strings "Admin/Manager" or "Warehouse" - which is
what most of them actually stored, because the stock modals hardcoded exactly those two.
"""

import uuid

import strawberry

from app.auth import current_user, resolve_display_name
from app.database import SessionLocal
from app.repositories import stock as stock_repository

from .converters import (
    deficiency_review_to_type,
    deficient_item_row_to_type,
    inventory_location_to_type,
    pull_request_item_to_type,
    stock_item_to_type,
)
from .enums import DeficientItemSource
from .inputs import (
    AdjustStockQuantityInput,
    AllocateStockToProjectInput,
    DestockInventoryInput,
    MoveStockLocationInput,
    ReclassifyStockItemInput,
    ReportDeficiencyAtAssemblyInput,
    ReportInventoryDeficiencyInput,
    ReportStockDeficiencyInput,
    ResolveDeficiencyInput,
    TransferInventoryInput,
)
from .types import (
    DeficiencyReview,
    DeficientItemRow,
    InventoryLocation,
    ReclassifyStockResult,
    SAReplacementResult,
    StockItem,
    TransferResult,
)


@strawberry.type
class StockQueries:
    @strawberry.field
    def stock_items(
        self,
        info: strawberry.Info,
        product_code_contains: str | None = None,
        hardware_category: str | None = None,
        aisle: str | None = None,
        only_deficient: bool = False,
        warehouse_id: strawberry.ID | None = None,
    ) -> list[StockItem]:
        with SessionLocal() as session:
            rows = stock_repository.get_stock_items(
                session,
                product_code_contains=product_code_contains,
                hardware_category=hardware_category,
                aisle=aisle,
                only_deficient=only_deficient,
                warehouse_id=uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            return [stock_item_to_type(r) for r in rows]

    @strawberry.field
    def stock_item(self, info: strawberry.Info, id: strawberry.ID) -> StockItem | None:
        with SessionLocal() as session:
            try:
                row = stock_repository.get_stock_item(session, uuid.UUID(str(id)))
            except Exception:
                return None
            return stock_item_to_type(row)

    @strawberry.field
    def deficient_items(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        source: DeficientItemSource | None = None,
    ) -> list[DeficientItemRow]:
        with SessionLocal() as session:
            rows = stock_repository.get_deficient_items(
                session,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
                source=source,
            )
            return [deficient_item_row_to_type(r) for r in rows]

    @strawberry.field
    def deficiency_reviews(
        self,
        info: strawberry.Info,
        inventory_location_id: strawberry.ID | None = None,
        stock_item_id: strawberry.ID | None = None,
        project_id: strawberry.ID | None = None,
    ) -> list[DeficiencyReview]:
        with SessionLocal() as session:
            rows = stock_repository.get_deficiency_reviews(
                session,
                inventory_location_id=(uuid.UUID(str(inventory_location_id)) if inventory_location_id else None),
                stock_item_id=uuid.UUID(str(stock_item_id)) if stock_item_id else None,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
            )
            return [deficiency_review_to_type(r) for r in rows]

    @strawberry.field
    def stock_matches_for_opening(self, info: strawberry.Info, opening_item_id: strawberry.ID) -> list[StockItem]:
        with SessionLocal() as session:
            rows = stock_repository.get_stock_matches_for_opening(session, uuid.UUID(str(opening_item_id)))
            return [stock_item_to_type(r) for r in rows]


@strawberry.type
class StockMutations:
    @strawberry.mutation
    def destock_inventory(self, info: strawberry.Info, input: DestockInventoryInput) -> StockItem:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.destock_inventory(
                session,
                inventory_location_id=uuid.UUID(str(input.inventory_location_id)),
                quantity=input.quantity,
                source=input.source,
                reason_text=input.reason_text,
                target_aisle=input.target_aisle,
                target_row=input.target_row,
                target_bay=input.target_bay,
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return stock_item_to_type(result)

    @strawberry.mutation
    def transfer_inventory(self, info: strawberry.Info, input: TransferInventoryInput) -> TransferResult:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.transfer_inventory(
                session,
                source_type=input.source_type.value,
                source_id=uuid.UUID(str(input.source_id)),
                quantity=input.quantity,
                dest_warehouse_id=uuid.UUID(str(input.dest_warehouse_id)),
                dest_aisle=input.dest_aisle,
                dest_row=input.dest_row,
                dest_bay=input.dest_bay,
                performed_by=actor,
            )
            session.commit()
            return TransferResult(
                success=result["success"],
                quantity=result["quantity"],
                dest_warehouse_id=strawberry.ID(str(result["dest_warehouse_id"])),
            )

    @strawberry.mutation
    def allocate_stock_to_project(self, info: strawberry.Info, input: AllocateStockToProjectInput) -> InventoryLocation:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.allocate_stock_to_project(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                project_id=uuid.UUID(str(input.project_id)),
                target_hardware_category=input.target_hardware_category,
                target_product_code=input.target_product_code,
                quantity=input.quantity,
                target_aisle=input.target_aisle,
                target_row=input.target_row,
                target_bay=input.target_bay,
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def adjust_stock_quantity(self, info: strawberry.Info, input: AdjustStockQuantityInput) -> StockItem:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.adjust_stock_quantity(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                new_quantity=input.new_quantity,
                reason_text=input.reason_text,
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return stock_item_to_type(result)

    @strawberry.mutation
    def move_stock_location(self, info: strawberry.Info, input: MoveStockLocationInput) -> StockItem:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.move_stock_location(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                new_aisle=input.new_aisle,
                new_row=input.new_row,
                new_bay=input.new_bay,
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return stock_item_to_type(result)

    @strawberry.mutation
    def assign_stock_item_location(
        self,
        info: strawberry.Info,
        stock_item_id: strawberry.ID,
        aisle: str,
        row: str,
        bay: str,
    ) -> StockItem:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.assign_stock_item_location(
                session,
                stock_item_id=uuid.UUID(str(stock_item_id)),
                aisle=aisle,
                row=row,
                bay=bay,
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return stock_item_to_type(result)

    @strawberry.mutation
    def mark_stock_item_unlocated(self, info: strawberry.Info, stock_item_id: strawberry.ID) -> StockItem:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = stock_repository.mark_stock_item_unlocated(
                session,
                stock_item_id=uuid.UUID(str(stock_item_id)),
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return stock_item_to_type(result)

    @strawberry.mutation
    def reclassify_stock_item(self, info: strawberry.Info, input: ReclassifyStockItemInput) -> ReclassifyStockResult:
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            new_row, original = stock_repository.reclassify_stock_item(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                new_hardware_category=input.new_hardware_category,
                new_product_code=input.new_product_code,
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=actor,
            )
            session.commit()
            session.refresh(new_row)
            if original is not None:
                session.refresh(original)
            return ReclassifyStockResult(
                reclassified_stock_item=stock_item_to_type(new_row),
                original_stock_item=stock_item_to_type(original) if original else None,
            )

    @strawberry.mutation
    def report_inventory_deficiency(
        self, info: strawberry.Info, input: ReportInventoryDeficiencyInput
    ) -> InventoryLocation:
        """Condemn units on a project inventory row. Open to any signed-in user - it makes stock
        unavailable to every other request in the project, so it must not be reachable anonymously."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            il = stock_repository.report_inventory_deficiency(
                session,
                inventory_location_id=uuid.UUID(str(input.inventory_location_id)),
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=actor,
            )
            session.commit()
            session.refresh(il)
            return inventory_location_to_type(il)

    @strawberry.mutation
    def report_stock_deficiency(self, info: strawberry.Info, input: ReportStockDeficiencyInput) -> StockItem:
        """Condemn units on a stock-pool row. Open to any signed-in user - same reasoning as
        reportInventoryDeficiency: it takes stock out of circulation."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            si = stock_repository.report_stock_deficiency(
                session,
                stock_item_id=uuid.UUID(str(input.stock_item_id)),
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=actor,
            )
            session.commit()
            session.refresh(si)
            return stock_item_to_type(si)

    @strawberry.mutation
    def report_deficiency_at_assembly(
        self, info: strawberry.Info, input: ReportDeficiencyAtAssemblyInput
    ) -> SAReplacementResult:
        """Flag a unit deficient at the bench. Open to any signed-in user - it writes project
        inventory and mints a replacement pull request, so it must not be reachable anonymously."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            il, pri = stock_repository.report_deficiency_at_assembly(
                session,
                sa_opening_item_id=uuid.UUID(str(input.shop_assembly_opening_item_id)),
                quantity=input.quantity,
                reason_text=input.reason_text,
                performed_by=actor,
            )
            session.commit()
            session.refresh(il)
            session.refresh(pri)
            return SAReplacementResult(
                inventory_location=inventory_location_to_type(il),
                replacement_pull_request_item=pull_request_item_to_type(pri),
            )

    @strawberry.mutation
    def resolve_deficiency(self, info: strawberry.Info, input: ResolveDeficiencyInput) -> DeficiencyReview:
        """Disposition a condemned batch (scrap, repair, RMA, destock). Open to any signed-in user -
        it moves or writes off real stock, so it must not be reachable anonymously."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            review = stock_repository.resolve_deficiency(
                session,
                inventory_location_id=(
                    uuid.UUID(str(input.inventory_location_id)) if input.inventory_location_id else None
                ),
                stock_item_id=(uuid.UUID(str(input.stock_item_id)) if input.stock_item_id else None),
                resolution=input.resolution,
                quantity=input.quantity,
                reason_text=input.reason_text,
                rma_reference=input.rma_reference,
                destock_source=input.destock_source,
                reviewed_by=actor,
            )
            session.commit()
            session.refresh(review)
            return deficiency_review_to_type(review)
