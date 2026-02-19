import uuid
from datetime import datetime, date
from typing import Optional

import strawberry

from .enums import (
    Classification,
    HardwareItemState,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    PullRequestItemType,
    OpeningItemState,
    ShopAssemblyRequestStatus,
    PullStatus,
    AssemblyStatus,
    NotificationType,
    ReconciliationStatus,
    ApproveOutcome,
)


@strawberry.type
class Opening:
    id: strawberry.ID
    project_id: strawberry.ID
    opening_number: str
    building: Optional[str]
    floor: Optional[str]
    location: Optional[str]
    location_to: Optional[str]
    location_from: Optional[str]
    hand: Optional[str]
    width: Optional[str]
    length: Optional[str]
    door_thickness: Optional[str]
    jamb_thickness: Optional[str]
    door_type: Optional[str]
    frame_type: Optional[str]
    interior_exterior: Optional[str]
    keying: Optional[str]
    heading_no: Optional[str]
    single_pair: Optional[str]
    assignment_multiplier: Optional[str]
    created_at: datetime
    updated_at: datetime


@strawberry.type
class HardwareItem:
    id: strawberry.ID
    project_id: strawberry.ID
    opening_id: strawberry.ID
    hardware_category: str
    product_code: str
    material_id: str
    item_quantity: int
    unit_cost: Optional[float]
    unit_price: Optional[float]
    list_price: Optional[float]
    vendor_discount: Optional[float]
    markup_pct: Optional[float]
    vendor_no: Optional[str]
    phase_code: Optional[str]
    item_category_code: Optional[str]
    product_group_code: Optional[str]
    submittal_id: Optional[str]
    classification: Optional[Classification]
    state: HardwareItemState
    po_line_item_id: Optional[strawberry.ID]
    created_at: datetime
    updated_at: datetime


@strawberry.type
class POLineItem:
    id: strawberry.ID
    po_id: strawberry.ID
    hardware_category: str
    product_code: str
    classification: Classification
    ordered_quantity: int
    received_quantity: int
    unit_cost: float
    created_at: datetime
    updated_at: datetime


@strawberry.type
class ReceiveLineItem:
    id: strawberry.ID
    receive_record_id: strawberry.ID
    po_line_item_id: strawberry.ID
    hardware_category: str
    product_code: str
    quantity_received: int
    created_at: datetime


@strawberry.type
class ReceiveRecord:
    id: strawberry.ID
    po_id: strawberry.ID
    received_at: datetime
    received_by: str
    created_at: datetime
    line_items: list[ReceiveLineItem]


@strawberry.type
class PurchaseOrder:
    id: strawberry.ID
    po_number: str
    project_id: strawberry.ID
    status: POStatus
    vendor_name: Optional[str]
    vendor_contact: Optional[str]
    expected_delivery_date: Optional[date]
    ordered_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime
    line_items: list[POLineItem]
    receive_records: list[ReceiveRecord]


@strawberry.type
class Project:
    id: strawberry.ID
    project_id: str
    description: Optional[str]
    job_site_name: Optional[str]
    address: Optional[str]
    city: Optional[str]
    state: Optional[str]
    zip: Optional[str]
    contractor: Optional[str]
    project_manager: Optional[str]
    application: Optional[str]
    submittal_job_no: Optional[str]
    submittal_assignment_count: Optional[int]
    estimator_code: Optional[str]
    titan_user_id: Optional[str]
    created_at: datetime
    updated_at: datetime
    openings: list[Opening]
    purchase_orders: list[PurchaseOrder]


@strawberry.type
class InventoryLocation:
    id: strawberry.ID
    project_id: strawberry.ID
    po_line_item_id: strawberry.ID
    receive_line_item_id: strawberry.ID
    hardware_category: str
    product_code: str
    quantity: int
    shelf: Optional[str]
    column: Optional[str]
    row: Optional[str]
    received_at: datetime
    created_at: datetime
    updated_at: datetime


@strawberry.type
class OpeningItemHardware:
    id: strawberry.ID
    opening_item_id: strawberry.ID
    product_code: str
    hardware_category: str
    quantity: int


@strawberry.type
class OpeningItem:
    id: strawberry.ID
    project_id: strawberry.ID
    opening_id: strawberry.ID
    opening_number: str
    building: Optional[str]
    floor: Optional[str]
    location: Optional[str]
    quantity: int
    assembly_completed_at: datetime
    state: OpeningItemState
    shelf: Optional[str]
    column: Optional[str]
    row: Optional[str]
    created_at: datetime
    updated_at: datetime
    installed_hardware: list[OpeningItemHardware]


@strawberry.type
class PullRequestItem:
    id: strawberry.ID
    pull_request_id: strawberry.ID
    item_type: PullRequestItemType
    opening_number: str
    opening_item_id: Optional[strawberry.ID]
    hardware_category: Optional[str]
    product_code: Optional[str]
    requested_quantity: int


@strawberry.type
class PullRequest:
    id: strawberry.ID
    request_number: str
    project_id: strawberry.ID
    source: PullRequestSource
    status: PullRequestStatus
    requested_by: str
    assigned_to: Optional[str]
    created_at: datetime
    updated_at: datetime
    approved_at: Optional[datetime]
    completed_at: Optional[datetime]
    cancelled_at: Optional[datetime]
    items: list[PullRequestItem]


@strawberry.type
class ShopAssemblyOpeningItem:
    id: strawberry.ID
    shop_assembly_opening_id: strawberry.ID
    hardware_category: str
    product_code: str
    quantity: int


@strawberry.type
class ShopAssemblyOpening:
    id: strawberry.ID
    shop_assembly_request_id: strawberry.ID
    opening_id: strawberry.ID
    pull_status: PullStatus
    assigned_to: Optional[str]
    assembly_status: AssemblyStatus
    completed_at: Optional[datetime]
    items: list[ShopAssemblyOpeningItem]
    # Resolved from Opening table (populated by myWork and assembleList queries)
    opening_number: Optional[str] = None
    building: Optional[str] = None
    floor: Optional[str] = None


@strawberry.type
class ShopAssemblyRequest:
    id: strawberry.ID
    request_number: str
    project_id: strawberry.ID
    status: ShopAssemblyRequestStatus
    created_by: str
    approved_by: Optional[str]
    rejected_by: Optional[str]
    rejection_reason: Optional[str]
    created_at: datetime
    approved_at: Optional[datetime]
    rejected_at: Optional[datetime]
    openings: list[ShopAssemblyOpening]


@strawberry.type
class PackingSlipItem:
    id: strawberry.ID
    packing_slip_id: strawberry.ID
    item_type: PullRequestItemType
    opening_item_id: Optional[strawberry.ID]
    opening_number: Optional[str]
    product_code: str
    hardware_category: str
    quantity: int


@strawberry.type
class PackingSlip:
    id: strawberry.ID
    packing_slip_number: str
    project_id: strawberry.ID
    shipped_by: str
    shipped_at: datetime
    pdf_file_path: str
    created_at: datetime
    items: list[PackingSlipItem]


@strawberry.type
class Notification:
    id: strawberry.ID
    project_id: strawberry.ID
    recipient_role: str
    type: NotificationType
    message: str
    is_read: bool
    created_at: datetime


# Composite output types

@strawberry.type
class FinalizeImportResult:
    project: Project
    purchase_orders: list[PurchaseOrder]
    shipping_out_pull_requests: list[PullRequest]
    shop_assembly_request: Optional[ShopAssemblyRequest]


@strawberry.type
class ApproveShopAssemblyResult:
    shop_assembly_request: ShopAssemblyRequest
    pull_request: PullRequest


@strawberry.type
class POStatistics:
    total: int
    draft: int
    ordered: int
    partially_received: int
    closed: int
    cancelled: int


@strawberry.type
class ProductCodeNode:
    product_code: str
    items: list[InventoryLocation]
    total_quantity: int


@strawberry.type
class InventoryHierarchyNode:
    hardware_category: str
    product_codes: list[ProductCodeNode]
    total_quantity: int


@strawberry.type
class ShipReadyLooseItem:
    opening_number: str
    hardware_category: str
    product_code: str
    available_quantity: int


@strawberry.type
class ShipReadyItems:
    opening_items: list[OpeningItem]
    loose_items: list[ShipReadyLooseItem]


@strawberry.type
class InventoryItemDetail:
    inventory_location: InventoryLocation
    po_number: str
    classification: Classification


@strawberry.type
class OpeningItemDetail:
    opening_item: OpeningItem
    installed_hardware: list[OpeningItemHardware]


@strawberry.type
class ApproveResult:
    pull_request: PullRequest
    outcome: ApproveOutcome
    notification: Optional[Notification]


@strawberry.type
class ReconciliationResult:
    opening_number: str
    hardware_category: str
    product_code: str
    quantity_needed: int
    quantity_available: int
    status: ReconciliationStatus
