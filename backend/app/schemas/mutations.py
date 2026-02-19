from typing import Optional
from datetime import date

import strawberry

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
        raise NotImplementedError("updatePO not yet implemented")

    @strawberry.mutation
    def mark_po_as_ordered(self, id: strawberry.ID) -> PurchaseOrder:
        raise NotImplementedError("markPOAsOrdered not yet implemented")

    @strawberry.mutation
    def cancel_po(self, id: strawberry.ID) -> PurchaseOrder:
        raise NotImplementedError("cancelPO not yet implemented")

    # Warehouse - Receiving
    @strawberry.mutation
    def create_receive(self, input: CreateReceiveInput) -> ReceiveRecord:
        raise NotImplementedError("createReceive not yet implemented")

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
        raise NotImplementedError("adjustInventoryQuantity not yet implemented")

    @strawberry.mutation
    def move_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        new_shelf: str,
        new_column: str,
        new_row: str,
    ) -> InventoryLocation:
        raise NotImplementedError("moveInventoryLocation not yet implemented")

    @strawberry.mutation
    def mark_inventory_unlocated(
        self, inventory_location_id: strawberry.ID
    ) -> InventoryLocation:
        raise NotImplementedError("markInventoryUnlocated not yet implemented")

    @strawberry.mutation
    def assign_inventory_location(
        self,
        inventory_location_id: strawberry.ID,
        shelf: str,
        column: str,
        row: str,
    ) -> InventoryLocation:
        raise NotImplementedError("assignInventoryLocation not yet implemented")

    @strawberry.mutation
    def move_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        shelf: str,
        column: str,
        row: str,
    ) -> OpeningItem:
        raise NotImplementedError("moveOpeningItemLocation not yet implemented")

    @strawberry.mutation
    def mark_opening_item_unlocated(
        self, opening_item_id: strawberry.ID
    ) -> OpeningItem:
        raise NotImplementedError("markOpeningItemUnlocated not yet implemented")

    @strawberry.mutation
    def assign_opening_item_location(
        self,
        opening_item_id: strawberry.ID,
        shelf: str,
        column: str,
        row: str,
    ) -> OpeningItem:
        raise NotImplementedError("assignOpeningItemLocation not yet implemented")

    # Notifications
    @strawberry.mutation
    def mark_notification_as_read(self, id: strawberry.ID) -> Notification:
        raise NotImplementedError("markNotificationAsRead not yet implemented")

    # Shop Assembly
    @strawberry.mutation
    def approve_shop_assembly_request(
        self, id: strawberry.ID
    ) -> ApproveShopAssemblyResult:
        raise NotImplementedError("approveShopAssemblyRequest not yet implemented")

    @strawberry.mutation
    def reject_shop_assembly_request(
        self, id: strawberry.ID, reason: str
    ) -> ShopAssemblyRequest:
        raise NotImplementedError("rejectShopAssemblyRequest not yet implemented")

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
