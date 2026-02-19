import uuid
from typing import Optional
from datetime import date

import strawberry

from app.database import SessionLocal
from app.repositories import po_repository, warehouse_repository, shop_assembly_repository
from .enums import POStatus
from .inputs import (
    FinalizeImportSessionInput,
    CreateReceiveInput,
    ConfirmShipmentInput,
    AssignOpeningsInput,
    CompleteOpeningInput,
)
from .types import (
    FinalizeImportResult,
    PurchaseOrder,
    ReceiveRecord,
    ApproveResult,
    PullRequest,
    PackingSlip,
    InventoryLocation,
    OpeningItem,
    Notification,
    ApproveShopAssemblyResult,
    ShopAssemblyRequest,
    ShopAssemblyOpening,
)
from .queries import (
    _po_to_type,
    _inventory_location_to_type,
    _opening_item_to_type,
    _receive_record_to_type,
    _shop_assembly_request_to_type,
    _pull_request_to_type,
)


@strawberry.type
class Mutation:
    # Import
    @strawberry.mutation
    def finalize_import_session(
        self, input: FinalizeImportSessionInput
    ) -> FinalizeImportResult:
        raise NotImplementedError("finalizeImportSession not yet implemented")

    # PO
    @strawberry.mutation
    def update_po(
        self,
        id: strawberry.ID,
        vendor_name: Optional[str] = None,
        vendor_contact: Optional[str] = None,
        expected_delivery_date: Optional[date] = None,
    ) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.update_po(
                session,
                uuid.UUID(str(id)),
                vendor_name,
                vendor_contact,
                expected_delivery_date,
            )
            session.commit()
            session.refresh(po)
            return _po_to_type(po)

    @strawberry.mutation
    def mark_po_as_ordered(self, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.mark_po_as_ordered(
                session, uuid.UUID(str(id))
            )
            session.commit()
            session.refresh(po)
            return _po_to_type(po)

    @strawberry.mutation
    def cancel_po(self, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.cancel_po(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(po)
            return _po_to_type(po)

    # Warehouse - Receiving
    @strawberry.mutation
    def create_receive(self, input: CreateReceiveInput) -> ReceiveRecord:
        po_id = uuid.UUID(str(input.po_id))
        received_by = input.received_by
        line_items_data = [
            {
                "po_line_item_id": uuid.UUID(str(li.po_line_item_id)),
                "quantity_received": li.quantity_received,
                "locations": [
                    {
                        "shelf": loc.shelf,
                        "column": loc.column,
                        "row": loc.row,
                        "quantity": loc.quantity,
                    }
                    for loc in li.locations
                ],
            }
            for li in input.line_items
        ]
        with SessionLocal() as session:
            receive_record = warehouse_repository.create_receive(
                session, po_id, received_by, line_items_data
            )
            session.commit()
            session.refresh(receive_record)
            # Eagerly load line_items for the response
            from sqlalchemy.orm import selectinload
            from sqlalchemy import select
            from app.models.receiving import ReceiveRecord as ReceiveRecordModel
            stmt = (
                select(ReceiveRecordModel)
                .options(selectinload(ReceiveRecordModel.line_items))
                .where(ReceiveRecordModel.id == receive_record.id)
            )
            receive_record = session.scalars(stmt).unique().first()
            return _receive_record_to_type(receive_record)

    # Warehouse - Pull Requests
    @strawberry.mutation
    def approve_pull_request(
        self, id: strawberry.ID, approved_by: str
    ) -> ApproveResult:
        raise NotImplementedError("approvePullRequest not yet implemented")

    @strawberry.mutation
    def complete_pull_request(self, id: strawberry.ID) -> PullRequest:
        raise NotImplementedError("completePullRequest not yet implemented")

    # Warehouse - Shipping
    @strawberry.mutation
    def confirm_shipment(self, input: ConfirmShipmentInput) -> PackingSlip:
        raise NotImplementedError("confirmShipment not yet implemented")

    # Warehouse - Admin Corrections
    @strawberry.mutation
    def adjust_inventory_quantity(
        self, inventory_location_id: strawberry.ID, adjustment: int, reason: str
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.adjust_inventory_quantity(
                session, uuid.UUID(str(inventory_location_id)), adjustment, reason
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def move_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        new_shelf: str,
        new_column: str,
        new_row: str,
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.move_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), new_shelf, new_column, new_row
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def mark_inventory_unlocated(
        self, inventory_location_id: strawberry.ID
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.mark_inventory_unlocated(
                session, uuid.UUID(str(inventory_location_id))
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def assign_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        shelf: str,
        column: str,
        row: str,
    ) -> InventoryLocation:
        with SessionLocal() as session:
            result = warehouse_repository.assign_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), shelf, column, row
            )
            session.commit()
            session.refresh(result)
            return _inventory_location_to_type(result)

    @strawberry.mutation
    def move_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        shelf: str,
        column: str,
        row: str,
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.move_opening_item_location(
                session, uuid.UUID(str(opening_item_id)), shelf, column, row
            )
            session.commit()
            session.refresh(result)
            return _opening_item_to_type(result)

    @strawberry.mutation
    def mark_opening_item_unlocated(
        self, opening_item_id: strawberry.ID
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.mark_opening_item_unlocated(
                session, uuid.UUID(str(opening_item_id))
            )
            session.commit()
            session.refresh(result)
            return _opening_item_to_type(result)

    @strawberry.mutation
    def assign_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        shelf: str,
        column: str,
        row: str,
    ) -> OpeningItem:
        with SessionLocal() as session:
            result = warehouse_repository.assign_opening_item_location(
                session, uuid.UUID(str(opening_item_id)), shelf, column, row
            )
            session.commit()
            session.refresh(result)
            return _opening_item_to_type(result)

    # Notifications
    @strawberry.mutation
    def mark_notification_as_read(self, id: strawberry.ID) -> Notification:
        raise NotImplementedError("markNotificationAsRead not yet implemented")

    # Shop Assembly
    @strawberry.mutation
    def approve_shop_assembly_request(
        self, id: strawberry.ID
    ) -> ApproveShopAssemblyResult:
        with SessionLocal() as session:
            sar, pr = shop_assembly_repository.approve_shop_assembly_request(
                session, uuid.UUID(str(id))
            )
            session.commit()
            session.refresh(sar)
            session.refresh(pr)
            return ApproveShopAssemblyResult(
                shop_assembly_request=_shop_assembly_request_to_type(sar),
                pull_request=_pull_request_to_type(pr),
            )

    @strawberry.mutation
    def reject_shop_assembly_request(
        self, id: strawberry.ID, reason: str
    ) -> ShopAssemblyRequest:
        with SessionLocal() as session:
            sar = shop_assembly_repository.reject_shop_assembly_request(
                session, uuid.UUID(str(id)), reason
            )
            session.commit()
            session.refresh(sar)
            return _shop_assembly_request_to_type(sar)

    @strawberry.mutation
    def assign_openings(
        self, input: AssignOpeningsInput
    ) -> list[ShopAssemblyOpening]:
        raise NotImplementedError("assignOpenings not yet implemented")

    @strawberry.mutation
    def remove_opening_from_user(
        self, opening_id: strawberry.ID
    ) -> ShopAssemblyOpening:
        raise NotImplementedError("removeOpeningFromUser not yet implemented")

    @strawberry.mutation
    def complete_opening(self, input: CompleteOpeningInput) -> OpeningItem:
        raise NotImplementedError("completeOpening not yet implemented")
