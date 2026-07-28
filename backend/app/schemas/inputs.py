from datetime import date

import strawberry

from .enums import (
    Classification,
    DeficiencyResolution,
    DestockSource,
    PullRequestItemType,
    ReturnDisposition,
    TransferSourceType,
)


@strawberry.input
class AdoptGpJobInput:
    """Adopt a live GP job (JC00102) as a UC Nexus project. job_name is the display name the
    frontend read from the live gpJobs picker at selection time, snapshotted onto the project -
    it is not kept in sync with GP afterward."""

    job_number: str
    job_name: str | None = None


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
    # Door-leaf count (#311): 1 (single) or 2 (pair), from the distinct parsed leaves.
    leaf_count: int | None = None


@strawberry.input
class HardwareItemInput:
    opening_number: str
    product_code: str
    hardware_category: str
    item_quantity: int
    # Door leaf this item belongs to (#311): 1 or 2, or null for frames.
    leaf: int | None = None
    unit_cost: float | None = None
    unit_price: float | None = None
    list_price: float | None = None
    vendor_discount: float | None = None
    markup_pct: float | None = None
    vendor_no: str | None = None
    manufacturer: str | None = None
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
    # Issue #216: the PM's requested date, captured at PO-request creation.
    preferred_delivery_date: date | None = None
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
    # Door leaf (#335): set on OPENING_ITEM lines from the assembled OpeningItem. Null on LOOSE.
    leaf: int | None = None
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
    # What the schedule says this leaf is owed. Never reduced by scarcity.
    quantity: int
    # What the requester could actually claim out of available inventory, 0..quantity. The allocator
    # step always sends it explicitly. **None means "fully allocated" (= quantity)**, which is what
    # keeps every non-wizard caller - tests, scripts, a stale tab - on the pre-allocation behaviour:
    # ask for the whole line, and fail the availability gate if it does not fit.
    allocated_quantity: int | None = None


@strawberry.input
class SAROpeningInput:
    opening_number: str
    # Door leaf this assembly work unit is for (#311): 1 or 2, or null (frame / legacy).
    leaf: int | None = None
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
    # The caller has seen the "incomplete - awaiting replacement" flag on the assembled leaves it is
    # shipping and wants them on the request anyway (#341). Without it, a flagged leaf is refused
    # with a VALIDATION_ERROR naming every flagged leaf. Warn + confirm, never silent, never a hard
    # block - deliberate short-shipping is a real workflow, it just has to be a decision.
    acknowledge_incomplete_leaves: bool = False


@strawberry.input
class CreatePOLineItemInput:
    hardware_category: str
    product_code: str
    ordered_quantity: int
    unit_cost: float
    classification: Classification | None = None
    order_as: str | None = None


@strawberry.input
class CreateDraftPOInput:
    """Issue #256: manual PO creation lands as a plain DRAFT - no relay, no GP fields. Registering
    the draft into GP (register_po_in_gp) is a separate, conscious user action where the GP vendor,
    buyer identity, and cost code are captured."""

    line_items: list[CreatePOLineItemInput]
    project_id: strawberry.ID | None = None
    # Optional link to a UC Nexus vendor record (contact info).
    vendor_id: strawberry.ID | None = None
    notes: str | None = None
    # Issue #216: the PM's requested date, captured at request creation.
    preferred_delivery_date: date | None = None
    # Issue #156: optional order-time dollar costs. Null means "not entered"; 0 is a valid value.
    shipping_cost: float | None = None
    tariff_amount: float | None = None


@strawberry.input
class RegisterPOLineItemInput:
    # The existing draft line this row maps to, or null for a line the user added in the register dialog.
    id: strawberry.ID | None = None
    hardware_category: str
    product_code: str
    ordered_quantity: int
    unit_cost: float
    classification: Classification | None = None
    order_as: str | None = None


@strawberry.input
class RegisterPOInput:
    """Register an imported DRAFT PO into GP (issue #175; brokered server-side as of issue #199). The
    resolver pushes this to GP via relay_call (create_po) BEFORE persisting anything. line_items is the
    (possibly edited) set pushed to GP, in the SAME order - the backend assigns gp_line_ord positionally
    from it."""

    po_id: strawberry.ID
    # The GP vendor picked live from the gpVendors(company) list (issue #200 - there's no local
    # vendor-to-GP mirror anymore). Snapshotted onto the PO for display.
    gp_vendor_id: str
    gp_vendor_name: str
    gp_company: str
    # GP buyer (POP00101), picked from the gpBuyers dropdown - always sent so the relay's own
    # per-workstation buyer fallback never decides it for a server-brokered call.
    buyer_id: str
    line_items: list[RegisterPOLineItemInput]
    # Optional link to a UC Nexus vendor record (contact info), independent of the GP vendor above.
    vendor_id: strawberry.ID | None = None
    # #316: attach a project to a draft that has none - a manually created stock PO, whose only chance
    # to gain one is here. Ignored when the PO already has a project (enforced in the repository, not
    # just the dialog): its lines were imported against that project's hardware schedule.
    project_id: strawberry.ID | None = None
    cost_code: str | None = None
    # Issue #156: optional order-time dollar costs. Null means "not entered"; 0 is a valid value.
    # shipping_cost also feeds GP's Freight (FRTAMNT) at push time (issue #257); tariff_amount stays
    # nexus-only (its own PO-document line, not a GP charge).
    shipping_cost: float | None = None
    tariff_amount: float | None = None
    # Issue #257: GP purchase tax detail (TX00201 TXDTLTYP=2, picked from gpTaxDetails; CAD only) plus
    # the Miscellaneous (MSCCHAMT) and Trade Discount (TRDISAMT) charges written to the GP PO header.
    tax_detail_id: str | None = None
    miscellaneous: float | None = None
    trade_discount: float | None = None
    # Issue #202 #1: client-generated key that makes this GP-first write idempotent on retry.
    idempotency_key: str = ""


@strawberry.input
class EnrollRelayInstallInput:
    """Posted by the relay during one-time setup (authenticated by the enrollment token, not Clerk)."""

    enrollment_token: str
    hostname: str
    secret: str


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
class TransferInventoryInput:
    source_type: TransferSourceType
    source_id: strawberry.ID
    quantity: int
    dest_warehouse_id: strawberry.ID
    dest_aisle: str
    dest_row: str
    dest_bay: str
    performed_by: str = ""


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
class UpdatePODocumentSettingsInput:
    """Patch for the single-row PO-document boilerplate (issue #230). Every field defaults to UNSET so
    an omitted field is left untouched; the admin form is a full-record editor so it sends them all."""

    tax_numbers: str | None = strawberry.UNSET
    mandatory_bullets: list[str] | None = strawberry.UNSET
    shipping_accounts: list[str] | None = strawberry.UNSET
    shipping_methods: list[str] | None = strawberry.UNSET
    customs_broker_block: str | None = strawberry.UNSET
    fsc_note: str | None = strawberry.UNSET
    usa_tariff_note: str | None = strawberry.UNSET
    usa_tariff_effective_until: date | None = strawberry.UNSET
    company_from_address: str | None = strawberry.UNSET
    payment_terms: str | None = strawberry.UNSET
    confirm_with: str | None = strawberry.UNSET
    footer_notes: str | None = strawberry.UNSET
    signature_note: str | None = strawberry.UNSET


@strawberry.input
class SavePODocumentDataInput:
    """The generate-dialog capture for a PO (issue #230). Sent whole on each save; upsert overwrites."""

    vendor_address: str | None = None
    buyer_name: str | None = None
    currency: str = "CAD"
    ship_to: str | None = None
    shipping_method: str | None = None
    proposal_number: str | None = None
    freight: float = 0
    miscellaneous: float = 0
    tax_amount: float = 0
    tax_label: str = "Taxes"
    tariff_amount: float = 0
    required_by_override: date | None = None
    include_fsc: bool = False
    include_usa_tariff: bool = False
    include_customs: bool = False


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
    row: str
    bay: str
    quantity: int
    deficient_quantity: int = 0


@strawberry.input
class CreateReceiveInput:
    """Issue #199: GP-first, server-side. received_by is no longer a client-supplied field - the
    resolver resolves the acting UC Nexus user from the Clerk token instead."""

    po_id: strawberry.ID
    warehouse_id: strawberry.ID | None = None
    line_items: list[ReceiveLineItemInput] = strawberry.field(default_factory=list)
    # Issue #202 #1: client-generated key (one per user action, re-sent on retry) that makes this
    # GP-first receive idempotent - a retry returns the already-created receive instead of posting a
    # SECOND GP receipt (replacing the deleted client-side gpReceiptPostedRef guard).
    idempotency_key: str = ""


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
class ShipmentReturnItemInput:
    packing_slip_item_id: strawberry.ID
    quantity: int
    disposition: ReturnDisposition
    rma_reference: str | None = None
    reason_text: str | None = None


@strawberry.input
class CreateShipmentReturnInput:
    packing_slip_id: strawberry.ID
    warehouse_id: strawberry.ID
    returned_by: str
    reference: str | None = None
    items: list[ShipmentReturnItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class AssignOpeningsInput:
    opening_ids: list[strawberry.ID] = strawberry.field(default_factory=list)
    # Stable Clerk user id the openings are claimed by (#324) - the key myWork filters on.
    assigned_to_user_id: str = ""
    # Human-readable display name stored alongside for the UI.
    assigned_to: str = ""


@strawberry.input
class AssemblyProgressItemInput:
    """One line of a progress save (#340).

    installed_quantity is the ABSOLUTE running total of units fitted to the leaf, so re-sending it is
    a no-op and a miscount can be corrected in either direction until the opening is completed. Omit
    it to leave the line's installed count alone.

    flag_deficient_quantity is INCREMENTAL - units being condemned now, on top of any already flagged.
    Each one is immediately returned to inventory flagged deficient and given a PR-REPL replacement
    pull line, which is why it is one-way and why a reason is required with it.
    """

    shop_assembly_opening_item_id: strawberry.ID
    installed_quantity: int | None = None
    flag_deficient_quantity: int | None = None
    deficient_reason: str | None = None


@strawberry.input
class RecordAssemblyProgressInput:
    opening_id: strawberry.ID
    items: list[AssemblyProgressItemInput] = strawberry.field(default_factory=list)
    # The assembler; recorded as the actor on the progress audit rows and on any deficiency return.
    performed_by: str | None = None


@strawberry.input
class InstallReplacementInput:
    """Fit arrived replacement hardware to an already-completed leaf (#341). The quantity can only
    come out of what the replacement pull actually delivered, so this cannot inflate a leaf."""

    shop_assembly_opening_item_id: strawberry.ID
    quantity: int
    performed_by: str | None = None


@strawberry.input
class StagePullOpeningsInput:
    """Confirm that the cart(s) for these openings of an approved shop-assembly pull are built (#343).

    Openings already staged are skipped, not refused, so a double-click or a stale checklist is a
    no-op. Staging the last one completes the pull."""

    pull_request_id: strawberry.ID
    opening_ids: list[strawberry.ID]
    staged_by: str


@strawberry.input
class CancelPullRequestInput:
    """Cancel an approved pull and return its hardware to inventory (#343).

    All-or-nothing: an opening whose assembly has started or finished blocks the whole cancellation,
    and the refusal names them. `reason` is optional but shown to whoever raised the pull."""

    id: strawberry.ID
    cancelled_by: str
    reason: str | None = None


@strawberry.input
class CompleteOpeningInput:
    opening_id: strawberry.ID
    aisle: str | None = None
    row: str | None = None
    bay: str | None = None
    completed_by: str | None = None


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
    target_row: str | None = None
    target_bay: str | None = None
    performed_by: str = ""


@strawberry.input
class AllocateStockToProjectInput:
    stock_item_id: strawberry.ID
    project_id: strawberry.ID
    target_hardware_category: str
    target_product_code: str
    quantity: int
    target_aisle: str | None = None
    target_row: str | None = None
    target_bay: str | None = None
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
    new_row: str
    new_bay: str
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
    """A location and how many of the added units land there (used by an inventory quantity override)."""

    aisle: str
    row: str
    bay: str
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
