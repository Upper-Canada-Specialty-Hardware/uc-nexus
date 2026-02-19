from typing import Optional

import strawberry

from .enums import Classification, PullRequestItemType


@strawberry.input
class ProjectInput:
    project_id: str
    description: Optional[str] = None
    job_site_name: Optional[str] = None
    address: Optional[str] = None
    city: Optional[str] = None
    state: Optional[str] = None
    zip: Optional[str] = None
    contractor: Optional[str] = None
    project_manager: Optional[str] = None
    application: Optional[str] = None
    submittal_job_no: Optional[str] = None
    submittal_assignment_count: Optional[int] = None
    estimator_code: Optional[str] = None
    titan_user_id: Optional[str] = None


@strawberry.input
class OpeningInput:
    opening_number: str
    building: Optional[str] = None
    floor: Optional[str] = None
    location: Optional[str] = None
    location_to: Optional[str] = None
    location_from: Optional[str] = None
    hand: Optional[str] = None
    width: Optional[str] = None
    length: Optional[str] = None
    door_thickness: Optional[str] = None
    jamb_thickness: Optional[str] = None
    door_type: Optional[str] = None
    frame_type: Optional[str] = None
    interior_exterior: Optional[str] = None
    keying: Optional[str] = None
    heading_no: Optional[str] = None
    single_pair: Optional[str] = None
    assignment_multiplier: Optional[str] = None


@strawberry.input
class HardwareItemInput:
    opening_number: str
    product_code: str
    material_id: str
    hardware_category: str
    item_quantity: int
    unit_cost: Optional[float] = None
    unit_price: Optional[float] = None
    list_price: Optional[float] = None
    vendor_discount: Optional[float] = None
    markup_pct: Optional[float] = None
    vendor_no: Optional[str] = None
    phase_code: Optional[str] = None
    item_category_code: Optional[str] = None
    product_group_code: Optional[str] = None
    submittal_id: Optional[str] = None


@strawberry.input
class HardwareItemRef:
    opening_number: str
    product_code: str
    material_id: str


@strawberry.input
class PODraftInput:
    po_number: str
    vendor_name: Optional[str] = None
    vendor_contact: Optional[str] = None
    hardware_item_refs: list[HardwareItemRef] = strawberry.field(default_factory=list)


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
    opening_item_id: Optional[strawberry.ID] = None
    hardware_category: Optional[str] = None
    product_code: Optional[str] = None
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
    hardware_items: Optional[list[HardwareItemInput]] = None
    po_drafts: Optional[list[PODraftInput]] = None
    classifications: Optional[list[ClassificationInput]] = None
    shipping_out_pr_drafts: Optional[list[ShippingOutPRDraftInput]] = None
    include_shop_assembly_request: bool = False
    shop_assembly_request_number: Optional[str] = None
    shop_assembly_openings: Optional[list[SAROpeningInput]] = None


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
    shelf: str
    column: str
    row: str
    quantity: int


@strawberry.input
class CreateReceiveInput:
    po_id: strawberry.ID
    received_by: str
    line_items: list[ReceiveLineItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class ShipmentItemInput:
    item_type: PullRequestItemType
    opening_item_id: Optional[strawberry.ID] = None
    opening_number: Optional[str] = None
    product_code: Optional[str] = None
    hardware_category: Optional[str] = None
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
    shelf: Optional[str] = None
    column: Optional[str] = None
    row: Optional[str] = None
