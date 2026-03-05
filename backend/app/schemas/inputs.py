import strawberry

from .enums import Classification, PullRequestItemType


@strawberry.input
class ProjectInput:
    project_id: str
    description: str | None = None
    job_site_name: str | None = None
    address: str | None = None
    city: str | None = None
    state: str | None = None
    zip: str | None = None
    contractor: str | None = None
    project_manager: str | None = None
    application: str | None = None
    submittal_job_no: str | None = None
    submittal_assignment_count: int | None = None
    estimator_code: str | None = None
    titan_user_id: str | None = None


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
    material_id: str
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
    material_id: str


@strawberry.input
class POLineItemAliasInput:
    hardware_category: str
    product_code: str
    vendor_alias: str


@strawberry.input
class PODraftInput:
    po_number: str
    vendor_name: str | None = None
    vendor_contact: str | None = None
    hardware_item_refs: list[HardwareItemRef] = strawberry.field(default_factory=list)
    line_item_aliases: list[POLineItemAliasInput] = strawberry.field(default_factory=list)


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
class FinalizeImportSessionInput:
    project: ProjectInput
    openings: list[OpeningInput] = strawberry.field(default_factory=list)
    hardware_items: list[HardwareItemInput] | None = None
    po_drafts: list[PODraftInput] | None = None
    classifications: list[ClassificationInput] | None = None
    shipping_out_pr_drafts: list[ShippingOutPRDraftInput] | None = None
    include_shop_assembly_request: bool = False
    shop_assembly_request_number: str | None = None
    shop_assembly_openings: list[SAROpeningInput] | None = None


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


@strawberry.input
class CreateReceiveInput:
    po_id: strawberry.ID
    received_by: str
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
