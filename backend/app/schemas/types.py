from datetime import date, datetime

import strawberry

from .enums import (
    ApproveOutcome,
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    Classification,
    DeficiencyResolution,
    DeficientItemSource,
    HardwareItemState,
    NotificationType,
    OpeningItemState,
    PODocumentType,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReconciliationStatus,
    ReturnDisposition,
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
class ProjectExcludedItem:
    hardware_category: str
    product_code: str


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
    manufacturer: str | None
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
class Vendor:
    id: strawberry.ID
    name: str
    contact_name: str | None
    email: str | None
    phone: str | None
    notes: str | None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class RelayInstallProvision:
    """Result of provisioning a relay install. enrollment_token is shown ONCE - it never comes back."""

    install_id: strawberry.ID
    label: str
    company: str
    enrollment_token: str
    enrollment_token_expires_at: datetime


@strawberry.type
class RelayEnrollResult:
    ok: bool
    install_id: strawberry.ID


@strawberry.type
class RelayInstallInfo:
    id: strawberry.ID
    label: str
    company: str
    hostname: str | None
    enrolled: bool
    enrolled_at: datetime | None
    last_seen_at: datetime | None
    created_at: datetime


@strawberry.type
class RelayStatus:
    connected: bool
    # The GP company the connected relay is enrolled for (null when disconnected). The PO/receive/adopt
    # dialogs drive their company selection from this so they never offer a company the live relay can't
    # serve - a mismatch would fail every gp_* read and reject a submit as RelayUnavailable (issue #202 #6).
    company: str | None = None


@strawberry.type
class GpJob:
    job_number: str
    job_name: str | None


@strawberry.type
class GpVendor:
    vendor_id: str
    vendor_name: str
    vendor_class: str | None
    status: int


@strawberry.type
class GpCostCode:
    cost_code: str  # two-segment number 'cc1-cc2' e.g. '310-000'
    description: str | None
    cost_element: int


@strawberry.type
class VendorCandidate:
    # A GP vendor proposed for a manufacturer. score is 0..100: 100 for a saved mapping hit, else the
    # fuzzy match of the vendor name to the manufacturer (issue #232).
    gp_vendor_id: str
    gp_vendor_name: str
    score: float


@strawberry.type
class VendorSuggestion:
    # The manufacturer that was resolved (echoed back for the dialog label). saved_mapping is true when
    # a persisted manufacturer->vendor mapping decided it (candidates then holds exactly that vendor at
    # score 100); false when candidates are the top-N live vendors ranked by fuzzy score.
    manufacturer: str
    saved_mapping: bool
    candidates: list[VendorCandidate]


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
    order_as: str | None
    gp_line_ord: int | None
    # Issue #232: derived (not stored) - the TITAN manufacturer of the HardwareItem rows this line
    # covers, for the PO dialog's vendor suggestion. Null when no linked item carries a manufacturer.
    manufacturer: str | None
    created_at: datetime
    updated_at: datetime


@strawberry.type
class PriorOrderAsForProduct:
    product_code: str
    values: list[str]


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
class RecentReceiveRecord:
    receive_record: ReceiveRecord
    po_number: str | None
    total_items_received: int


@strawberry.type
class PODocumentInfo:
    id: strawberry.ID
    po_id: strawberry.ID
    file_name: str
    content_type: str
    file_size: int
    document_type: PODocumentType
    uploaded_at: datetime
    download_url: str


@strawberry.type
class PODocumentData:
    """Per-PO captured gap data for the generated supplier PO document (issue #230)."""

    id: strawberry.ID
    po_id: strawberry.ID
    vendor_address: str | None
    buyer_name: str | None
    currency: str
    ship_to: str | None
    shipping_method: str | None
    proposal_number: str | None
    freight: float
    miscellaneous: float
    tax_amount: float
    tax_label: str
    tariff_amount: float
    required_by_override: date | None
    include_fsc: bool
    include_usa_tariff: bool
    include_customs: bool


@strawberry.type
class PODocumentSettings:
    """Admin-configurable boilerplate for the generated supplier PO document (issue #230)."""

    tax_numbers: str
    mandatory_bullets: list[str]
    shipping_accounts: list[str]
    shipping_methods: list[str]
    customs_broker_block: str
    fsc_note: str
    usa_tariff_note: str
    usa_tariff_effective_until: date | None
    company_from_address: str
    payment_terms: str
    confirm_with: str
    footer_notes: str
    signature_note: str
    updated_at: datetime


@strawberry.type
class GpPoTotals:
    """GP-computed PO header totals (POP10100) read live via the relay, to auto-fill the generated
    supplier PO document (issue #230). Only available for a PO that exists in GP."""

    po_number: str
    subtotal: float
    freight: float
    miscellaneous: float
    tax_amount: float


@strawberry.type
class ProjectShipTo:
    """The job-site address of a project, used to build the "deliver to site" ship-to block on the
    generated PO document (issue #230). A lean projection so the PO list query stays cheap."""

    id: strawberry.ID
    project_id: str
    job_site_name: str | None
    address: str | None
    city: str | None
    state: str | None
    zip: str | None


@strawberry.type
class PurchaseOrder:
    id: strawberry.ID
    po_number: str | None
    request_number: str
    project_id: strawberry.ID | None
    status: POStatus
    cost_code: str | None
    gp_company: str | None
    gp_vendor_id: str | None
    vendor_name_snapshot: str | None
    buyer_id: str | None
    vendor: Vendor | None
    vendor_quote_number: str | None
    shipping_cost: float | None
    tariff_amount: float | None
    notes: str | None
    expected_delivery_date: date | None
    ordered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    line_items: list[POLineItem]
    receive_records: list[ReceiveRecord]
    documents: list[PODocumentInfo]
    document_data: PODocumentData | None = None


@strawberry.type
class Project:
    id: strawberry.ID
    project_id: str
    description: str | None
    client: str | None
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
    off_site_storage_agreement: bool
    gc_contact_name: str | None
    gc_phone: str | None
    gc_email: str | None
    created_at: datetime
    updated_at: datetime
    opening_count: int
    openings: list[Opening]
    purchase_orders: list[PurchaseOrder]


@strawberry.type
class ProjectScheduleHardwareItem:
    opening_number: str
    product_code: str
    material_id: str
    hardware_category: str
    item_quantity: int
    unit_cost: float | None
    unit_price: float | None
    list_price: float | None
    vendor_discount: float | None
    markup_pct: float | None
    vendor_no: str | None
    manufacturer: str | None
    phase_code: str | None
    item_category_code: str | None
    product_group_code: str | None
    submittal_id: str | None


@strawberry.type
class ProjectHardwareSchedule:
    project: Project
    openings: list[Opening]
    hardware_items: list[ProjectScheduleHardwareItem]


@strawberry.type
class InventoryLocation:
    id: strawberry.ID
    project_id: strawberry.ID
    po_line_item_id: strawberry.ID | None
    receive_line_item_id: strawberry.ID | None
    stock_item_id: strawberry.ID | None
    warehouse_id: strawberry.ID | None
    hardware_category: str
    product_code: str
    quantity: int
    deficient_quantity: int
    available: int
    aisle: str | None
    row: str | None
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
    warehouse_id: strawberry.ID | None
    opening_number: str
    building: str | None
    floor: str | None
    location: str | None
    quantity: int
    assembly_completed_at: datetime
    state: OpeningItemState
    aisle: str | None
    row: str | None
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
    # Legacy SAR parent (nullable since #222); openings now hang off pull_request_id.
    shop_assembly_request_id: strawberry.ID | None
    pull_request_id: strawberry.ID | None
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
class ReturnableLine:
    """A loose packing-slip line plus how much of it is still returnable."""

    packing_slip_item_id: strawberry.ID
    opening_number: str | None
    product_code: str
    hardware_category: str
    shipped_quantity: int
    returned_quantity: int
    returnable_quantity: int


@strawberry.type
class ShipmentReturnItem:
    id: strawberry.ID
    shipment_return_id: strawberry.ID
    packing_slip_item_id: strawberry.ID
    disposition: ReturnDisposition
    quantity: int
    hardware_category: str
    product_code: str
    opening_number: str | None
    rma_reference: str | None
    reason_text: str | None
    resulting_inventory_location_id: strawberry.ID | None
    resulting_stock_item_id: strawberry.ID | None
    created_at: datetime


@strawberry.type
class ShipmentReturn:
    id: strawberry.ID
    packing_slip_id: strawberry.ID
    warehouse_id: strawberry.ID
    returned_by: str
    returned_at: datetime
    reference: str | None
    created_at: datetime
    items: list[ShipmentReturnItem]


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
    # Legacy SAR field, always None since #222 retired the SAR flow. Kept for the result contract.
    shop_assembly_request: ShopAssemblyRequest | None
    # The shop-assembly PullRequest minted directly by "Start a Task" (#222). None unless the
    # import created one. This is what the import success UI confirms.
    shop_assembly_pull_request: PullRequest | None = None


@strawberry.type
class POStatistics:
    total: int
    draft: int
    gp_registered: int
    vendor_confirmed: int
    partially_received: int
    closed: int
    cancelled: int


@strawberry.type
class ProductCodeNode:
    product_code: str
    items: list[InventoryLocation]
    total_quantity: int
    total_value: float


@strawberry.type
class InventoryHierarchyNode:
    hardware_category: str
    product_codes: list[ProductCodeNode]
    total_quantity: int
    total_value: float


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
    po_number: str | None
    classification: Classification | None
    unit_cost: float | None


@strawberry.type
class OpeningItemDetail:
    opening_item: OpeningItem
    installed_hardware: list[OpeningItemHardware]


@strawberry.type
class InventoryShortfall:
    """One shorted (hardware_category, product_code) combo surfaced by an inventory-sufficiency
    gate (#224): requested vs available (quantity - deficient_quantity), and the gap."""

    hardware_category: str
    product_code: str
    requested: int
    available: int
    short: int


@strawberry.type
class ApproveResult:
    pull_request: PullRequest
    outcome: ApproveOutcome
    notification: Notification | None
    # Populated when outcome is INSUFFICIENT: the exact per-combo shortfall shown inline to the
    # approver. Empty on APPROVED.
    shortfalls: list[InventoryShortfall] = strawberry.field(default_factory=list)


@strawberry.type
class ReconciliationResult:
    opening_number: str
    hardware_category: str
    product_code: str
    quantity: int
    status: ReconciliationStatus


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


@strawberry.type
class VendorInventoryNode:
    vendor_name: str
    product_codes: list[ProductCodeNode]
    total_quantity: int
    total_value: float


@strawberry.type
class LocationUtilizationEntry:
    warehouse_id: strawberry.ID | None
    aisle: str
    row: str | None
    bay: str | None
    bin: str | None
    item_count: int
    total_quantity: int


@strawberry.type
class LocationContents:
    inventory_items: list[InventoryItemDetail]
    opening_items: list[OpeningItem]
    stock_items: list["StockItem"]


@strawberry.type
class LocationVariant:
    aisle: str | None
    bay: str | None
    bin: str | None


@strawberry.type
class LocationDuplicateGroup:
    canonical_aisle: str | None
    canonical_bay: str | None
    canonical_bin: str | None
    variants: list[LocationVariant]


@strawberry.type
class LocationDistinctValues:
    aisles: list[str]
    bays: list[str]
    bins: list[str]


@strawberry.type
class LocationMergeResult:
    inventory_locations: int
    opening_items: int
    stock_items: int


@strawberry.type
class BackOrderedItem:
    hardware_category: str
    product_code: str
    ordered_quantity: int
    received_quantity: int
    outstanding_quantity: int
    unit_cost: float
    po_number: str | None
    vendor_name: str | None
    expected_delivery_date: date | None


@strawberry.type
class WarehouseDashboard:
    total_item_count: int
    total_value: float
    unlocated_count: int
    pending_pull_shop: int
    pending_pull_shipping: int
    received_last_7_days: int
    back_ordered_count: int


@strawberry.type
class ProjectProgressByProduct:
    hardware_category: str
    product_code: str
    required_quantity: int
    po_drafted: int
    ordered_quantity: int
    received_quantity: int
    back_ordered: int
    shipped_out: int


@strawberry.type
class AuditLogEntry:
    id: strawberry.ID
    project_id: strawberry.ID | None
    entity_type: AuditEntityType
    entity_id: strawberry.ID
    action: AuditAction
    detail: strawberry.scalars.JSON | None
    performed_by: str
    created_at: datetime


@strawberry.type
class TransferResult:
    success: bool
    quantity: int
    dest_warehouse_id: strawberry.ID


@strawberry.type
class Warehouse:
    id: strawberry.ID
    name: str
    code: str
    address: str | None
    city: str | None
    province: str | None
    postal_code: str | None
    is_primary: bool
    is_active: bool
    created_at: datetime
    updated_at: datetime


@strawberry.type
class StockItem:
    id: strawberry.ID
    warehouse_id: strawberry.ID | None
    hardware_category: str
    product_code: str
    quantity: int
    deficient_quantity: int
    available: int
    aisle: str | None
    bay: str | None
    bin: str | None
    received_at: datetime
    created_at: datetime
    updated_at: datetime


@strawberry.type
class DeficiencyReview:
    id: strawberry.ID
    inventory_location_id: strawberry.ID | None
    stock_item_id: strawberry.ID | None
    resolution: DeficiencyResolution
    quantity: int
    reason_text: str | None
    rma_reference: str | None
    reviewed_by: str
    reviewed_at: datetime
    resulting_stock_item_id: strawberry.ID | None


@strawberry.type
class DeficientItemRow:
    source: DeficientItemSource
    inventory_location_id: strawberry.ID | None
    stock_item_id: strawberry.ID | None
    project_id: strawberry.ID | None
    hardware_category: str
    product_code: str
    deficient_quantity: int
    aisle: str | None
    bay: str | None
    bin: str | None


@strawberry.type
class ReclassifyStockResult:
    reclassified_stock_item: "StockItem"
    original_stock_item: "StockItem | None"


@strawberry.type
class SAReplacementResult:
    inventory_location: "InventoryLocation"
    replacement_pull_request_item: "PullRequestItem"


@strawberry.type
class ClerkUser:
    id: str
    first_name: str
    last_name: str
    email: str
    roles: list[str]
    image_url: str


@strawberry.type
class HomeDashboardStats:
    open_po_count: int
    pending_pull_request_count: int
    items_pending_receiving: int
    project_count: int


@strawberry.type
class ShopAssemblyStats:
    active_pull_request_count: int


@strawberry.type
class AdminStats:
    vendor_count: int
    user_count: int
    hardware_item_count: int
    opening_count: int
