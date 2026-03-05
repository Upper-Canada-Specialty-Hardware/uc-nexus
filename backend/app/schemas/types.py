from datetime import date, datetime

import strawberry

from .enums import (
    ApproveOutcome,
    AssemblyStatus,
    Classification,
    HardwareItemState,
    NotificationType,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReconciliationStatus,
    ShopAssemblyRequestStatus,
)


@strawberry.type
class Opening:
    id: strawberry.ID
    project_id: strawberry.ID
    opening_number: str
    building: str | None
    floor: str | None
    location: str | None
    location_to: str | None
    location_from: str | None
    hand: str | None
    width: str | None
    length: str | None
    door_thickness: str | None
    jamb_thickness: str | None
    door_type: str | None
    frame_type: str | None
    interior_exterior: str | None
    keying: str | None
    heading_no: str | None
    single_pair: str | None
    assignment_multiplier: str | None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class HardwareItem:
    id: strawberry.ID
    project_id: strawberry.ID
    opening_id: strawberry.ID
    hardware_category: str
    product_code: str
    material_id: str | None
    item_quantity: int
    unit_cost: float | None
    unit_price: float | None
    list_price: float | None
    vendor_discount: float | None
    markup_pct: float | None
    vendor_no: str | None
    phase_code: str | None
    item_category_code: str | None
    product_group_code: str | None
    submittal_id: str | None
    classification: Classification | None
    state: HardwareItemState
    po_line_item_id: strawberry.ID | None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class POLineItem:
    id: strawberry.ID
    po_id: strawberry.ID
    hardware_category: str
    product_code: str
    classification: Classification | None
    ordered_quantity: int
    received_quantity: int
    unit_cost: float
    vendor_alias: str | None
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
    vendor_name: str | None
    vendor_contact: str | None
    expected_delivery_date: date | None
    ordered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    line_items: list[POLineItem]
    receive_records: list[ReceiveRecord]


@strawberry.type
class Project:
    id: strawberry.ID
    project_id: str
    description: str | None
    job_site_name: str | None
    address: str | None
    city: str | None
    state: str | None
    zip: str | None
    contractor: str | None
    project_manager: str | None
    application: str | None
    submittal_job_no: str | None
    submittal_assignment_count: int | None
    estimator_code: str | None
    titan_user_id: str | None
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
    aisle: str | None
    bay: str | None
    bin: str | None
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
    building: str | None
    floor: str | None
    location: str | None
    quantity: int
    assembly_completed_at: datetime
    state: OpeningItemState
    aisle: str | None
    bay: str | None
    bin: str | None
    created_at: datetime
    updated_at: datetime
    installed_hardware: list[OpeningItemHardware]


@strawberry.type
class PullRequestItem:
    id: strawberry.ID
    pull_request_id: strawberry.ID
    item_type: PullRequestItemType
    opening_number: str
    opening_item_id: strawberry.ID | None
    hardware_category: str | None
    product_code: str | None
    requested_quantity: int


@strawberry.type
class PullRequest:
    id: strawberry.ID
    request_number: str
    project_id: strawberry.ID
    source: PullRequestSource
    status: PullRequestStatus
    requested_by: str
    assigned_to: str | None
    created_at: datetime
    updated_at: datetime
    approved_at: datetime | None
    completed_at: datetime | None
    cancelled_at: datetime | None
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
    assigned_to: str | None
    assembly_status: AssemblyStatus
    completed_at: datetime | None
    items: list[ShopAssemblyOpeningItem]
    # Resolved from Opening table (populated by myWork and assembleList queries)
    opening_number: str | None = None
    building: str | None = None
    floor: str | None = None


@strawberry.type
class ShopAssemblyRequest:
    id: strawberry.ID
    request_number: str
    project_id: strawberry.ID
    status: ShopAssemblyRequestStatus
    created_by: str
    approved_by: str | None
    rejected_by: str | None
    rejection_reason: str | None
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    openings: list[ShopAssemblyOpening]


@strawberry.type
class PackingSlipItem:
    id: strawberry.ID
    packing_slip_id: strawberry.ID
    item_type: PullRequestItemType
    opening_item_id: strawberry.ID | None
    opening_number: str | None
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
    shop_assembly_request: ShopAssemblyRequest | None


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
    classification: Classification | None


@strawberry.type
class OpeningItemDetail:
    opening_item: OpeningItem
    installed_hardware: list[OpeningItemHardware]


@strawberry.type
class ApproveResult:
    pull_request: PullRequest
    outcome: ApproveOutcome
    notification: Notification | None


@strawberry.type
class ReconciliationResult:
    opening_number: str
    hardware_category: str
    product_code: str
    quantity: int
    status: ReconciliationStatus


@strawberry.type
class HardwareSummaryRow:
    hardware_category: str
    product_code: str
    po_drafted: int
    ordered: int
    received: int
    back_ordered: int
    shipped_out: int


@strawberry.type
class OpeningHardwareStatusItem:
    hardware_category: str
    product_code: str
    item_quantity: int
    status: str


@strawberry.type
class OpeningHardwareStatus:
    opening_number: str
    building: str | None
    floor: str | None
    location: str | None
    items: list[OpeningHardwareStatusItem]
