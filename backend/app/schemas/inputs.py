import strawberry

from .enums import Classification, DeficiencyResolution, DestockSource, PullRequestItemType


@strawberry.input
class CreateProjectInput:
    project_id: str
    description: str
    client: str


@strawberry.input
class UpdateProjectInput:
    description: str | None = None
    client: str | None = None
    job_site_name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contractor: str | None = None
    project_manager: str | None = None
    application: str | None = None
    gc_contact_name: str | None = None
    gc_phone: str | None = None
    gc_email: str | None = None
    off_site_storage_agreement: bool | None = None


@strawberry.input
class OpeningInput:
    opening_number: str
    building: str | None = None
    floor: str | None = None
    location: str | None = None
    location_to: str | None = None
    location_from: str | None = None
    hand: str | None = None
    width: str | None = None
    length: str | None = None
    door_thickness: str | None = None
    jamb_thickness: str | None = None
    door_type: str | None = None
    frame_type: str | None = None
    interior_exterior: str | None = None
    keying: str | None = None
    heading_no: str | None = None
    single_pair: str | None = None
    assignment_multiplier: str | None = None


@strawberry.input
class HardwareItemInput:
    opening_number: str
    product_code: str
    hardware_category: str
    item_quantity: int
    unit_cost: float | None = None
    unit_price: float | None = None
    list_price: float | None = None
    vendor_discount: float | None = None
    markup_pct: float | None = None
    vendor_no: str | None = None
    phase_code: str | None = None
    item_category_code: str | None = None
    product_group_code: str | None = None
    submittal_id: str | None = None


@strawberry.input
class HardwareItemRef:
    opening_number: str
    product_code: str
    hardware_category: str


@strawberry.input
class POLineItemOrderAsInput:
    hardware_category: str
    product_code: str
    order_as: str


@strawberry.input
class PODraftInput:
    po_number: str | None = None
    vendor_id: strawberry.ID | None = None
    notes: str | None = None
    hardware_item_refs: list[HardwareItemRef] = strawberry.field(default_factory=list)
    line_item_aliases: list[POLineItemOrderAsInput] = strawberry.field(default_factory=list)


@strawberry.input
class ClassificationInput:
    hardware_category: str
    product_code: str
    unit_cost: float
    classification: Classification


@strawberry.input
class ShippingOutPRDraftItemInput:
    item_type: PullRequestItemType
    opening_number: str
    opening_item_id: strawberry.ID | None = None
    hardware_category: str | None = None
    product_code: str | None = None
    requested_quantity: int = 1


@strawberry.input
class ShippingOutPRDraftInput:
    request_number: str
    requested_by: str
    items: list[ShippingOutPRDraftItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class SAROpeningItemInput:
    hardware_category: str
    product_code: str
    quantity: int


@strawberry.input
class SAROpeningInput:
    opening_number: str
    items: list[SAROpeningItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class ExcludedItemInput:
    hardware_category: str
    product_code: str


@strawberry.input
class FinalizeImportSessionInput:
    project_id: strawberry.ID
    openings: list[OpeningInput] = strawberry.field(default_factory=list)
    hardware_items: list[HardwareItemInput] | None = None
    po_drafts: list[PODraftInput] | None = None
    classifications: list[ClassificationInput] | None = None
    excluded_items: list[ExcludedItemInput] | None = None
    shipping_out_pr_drafts: list[ShippingOutPRDraftInput] | None = None
    include_shop_assembly_request: bool = False
    shop_assembly_request_number: str | None = None
    shop_assembly_openings: list[SAROpeningInput] | None = None
    # When true, this finalize overrides the existing schedule: existing HardwareItem
    # rows are wiped (including IN_PO ones) and openings absent from the new input
    # are deleted. Downstream POs/receiving/SAR/inventory aggregates are preserved.
    replace_schedule: bool = False


@strawberry.input
class CreatePOLineItemInput:
    hardware_category: str
    product_code: str
    ordered_quantity: int
    unit_cost: float
    classification: Classification | None = None
    order_as: str | None = None


@strawberry.input
class CreatePOInput:
    line_items: list[CreatePOLineItemInput]
    project_id: strawberry.ID | None = None
    vendor_id: strawberry.ID | None = None
    notes: str | None = None


@strawberry.input
class CreateVendorInput:
    name: str
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


@strawberry.input
class UpdateVendorInput:
    name: str | None = None
    contact_name: str | None = None
    email: str | None = None
    phone: str | None = None
    notes: str | None = None


@strawberry.input
class CreateWarehouseInput:
    name: str
    code: str
    address: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    is_primary: bool = False
    is_active: bool = True


@strawberry.input
class UpdateWarehouseInput:
    name: str | None = None
    code: str | None = None
    address: str | None = None
    city: str | None = None
    province: str | None = None
    postal_code: str | None = None
    is_primary: bool | None = None
    is_active: bool | None = None


@strawberry.input
class ReconciliationItemInput:
    opening_number: str
    hardware_category: str
    product_code: str
    quantity_needed: int


@strawberry.input
class ReceiveLineItemInput:
    po_line_item_id: strawberry.ID
    quantity_received: int
    locations: list["LocationInput"] = strawberry.field(default_factory=list)


@strawberry.input
class LocationInput:
    aisle: str
    bay: str
    bin: str
    quantity: int
    deficient_quantity: int = 0


@strawberry.input
class CreateReceiveInput:
    po_id: strawberry.ID
    received_by: str
    warehouse_id: strawberry.ID | None = None
    line_items: list[ReceiveLineItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class ShipmentItemInput:
    item_type: PullRequestItemType
    opening_item_id: strawberry.ID | None = None
    opening_number: str | None = None
    product_code: str | None = None
    hardware_category: str | None = None
    quantity: int = 1


@strawberry.input
class ConfirmShipmentInput:
    project_id: strawberry.ID
    packing_slip_number: str
    shipped_by: str
    items: list[ShipmentItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class AssignOpeningsInput:
    opening_ids: list[strawberry.ID] = strawberry.field(default_factory=list)
    assigned_to: str = ""


@strawberry.input
class CompleteOpeningInput:
    opening_id: strawberry.ID
    aisle: str | None = None
    bay: str | None = None
    bin: str | None = None


# ---------------------------------------------------------------------------
# Stock pool + deficiency inputs
# ---------------------------------------------------------------------------


@strawberry.input
class DestockInventoryInput:
    inventory_location_id: strawberry.ID
    quantity: int
    source: DestockSource
    reason_text: str | None = None
    target_aisle: str | None = None
    target_bay: str | None = None
    target_bin: str | None = None
    performed_by: str = ""


@strawberry.input
class AllocateStockToProjectInput:
    stock_item_id: strawberry.ID
    project_id: strawberry.ID
    target_hardware_category: str
    target_product_code: str
    quantity: int
    target_aisle: str | None = None
    target_bay: str | None = None
    target_bin: str | None = None
    performed_by: str = ""


@strawberry.input
class AdjustStockQuantityInput:
    stock_item_id: strawberry.ID
    new_quantity: int
    reason_text: str
    performed_by: str = ""


@strawberry.input
class MoveStockLocationInput:
    stock_item_id: strawberry.ID
    new_aisle: str
    new_bay: str
    new_bin: str
    performed_by: str = ""


@strawberry.input
class ReclassifyStockItemInput:
    stock_item_id: strawberry.ID
    new_hardware_category: str
    new_product_code: str
    quantity: int
    reason_text: str | None = None
    performed_by: str = ""


@strawberry.input
class ReportInventoryDeficiencyInput:
    inventory_location_id: strawberry.ID
    quantity: int
    reason_text: str | None = None
    performed_by: str = ""


@strawberry.input
class OverrideDestinationInput:
    """A bin and how many of the added units land there (used by an inventory quantity override)."""

    aisle: str
    bay: str
    bin: str
    quantity: int


@strawberry.input
class OverrideInventoryQuantityInput:
    inventory_location_id: strawberry.ID
    new_quantity: int
    reason_text: str
    # required when new_quantity increases the row; ignored on a decrease. quantities must sum to the delta.
    destinations: list[OverrideDestinationInput] = strawberry.field(default_factory=list)
    performed_by: str = ""


@strawberry.input
class ReportStockDeficiencyInput:
    stock_item_id: strawberry.ID
    quantity: int
    reason_text: str | None = None
    performed_by: str = ""


@strawberry.input
class ReportDeficiencyAtAssemblyInput:
    shop_assembly_opening_item_id: strawberry.ID
    source_inventory_location_id: strawberry.ID
    quantity: int
    reason_text: str | None = None
    performed_by: str = ""


@strawberry.input
class ResolveDeficiencyInput:
    # exactly one of inventory_location_id / stock_item_id must be set
    inventory_location_id: strawberry.ID | None = None
    stock_item_id: strawberry.ID | None = None
    resolution: DeficiencyResolution = DeficiencyResolution.LEAVE_AS_DEFICIENT
    quantity: int = 1
    reason_text: str | None = None
    rma_reference: str | None = None
    destock_source: DestockSource | None = None
    reviewed_by: str = ""
