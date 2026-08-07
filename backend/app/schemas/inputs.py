from datetime import date

import strawberry

from .enums import (
    Classification,
    DeficiencyResolution,
    DestockSource,
    PullRequestItemType,
    ReceiveDecisionChoice,
    ReturnDisposition,
    TransferSourceType,
)


@strawberry.input
class CostCodeSelectionInput:
    """One cost code to provision on a job at the moment it is created (#448).

    This names WHICH code out of GP's own master (JC40202) to put on the job, and nothing else. Every
    value that lands in JC00701 - the alias, the description, and above all the GL account index -
    is read from GP's config at create time: the account comes from JC40302's (division, cost element)
    mapping, never from Nexus configuration and never from anything the user typed. That is the same
    provenance principle #427 and #430 settled for everything Nexus writes into GP.

    The cost element travels with the number because the master is keyed on both - the same code
    number exists once per element, and the account mapping is per element too."""

    cost_code: str
    cost_element: int


@strawberry.input
class CreateGpJobInput:
    """Originate a job in GP through the WennSoft job proc, which then becomes a UC Nexus project
    (#380).

    The eight required fields are exactly the eight wsiJCJobMaster demands - established by validating
    a clean call and then dropping each field in turn. Everything else on that proc (215 inputs, all
    defaulted) is left alone, except the eight below that the issue asks to expose.

    None on an optional field means "not sent", so GP keeps its own default. That is deliberately
    different from sending a blank string, which would overwrite it.

    `cost_codes` is the one thing here that is not a wsiJCJobMaster parameter: the proc creates a job
    with zero JC00701 rows, so the codes are provisioned alongside it (#448). An empty list is
    accepted and means exactly that - a job with no cost structure, which leaves the register-PO
    cost-code dropdown empty and quarantines the project on the next gp_job_sync stamp (rule one of
    the #425 setup check) until somebody adds codes in GP."""

    job_number: str
    job_name: str
    division: str
    customer_number: str
    job_address_code: str
    billto_address_code: str
    tax_schedule_id: str
    # Checked against GP's fiscal calendar, not the clock: the proc reads this date and refuses a
    # closed period. A sandbox whose calendar has lapsed rejects today's date - correctly.
    created_date: date

    estimator_id: str | None = None
    ws_manager_id: str | None = None
    ws_project_number: str | None = None
    bill_customer_number: str | None = None
    use_tax_schedule: str | None = None
    schedule_start_date: date | None = None
    scheduled_completion_date: date | None = None
    bid_due_date: date | None = None

    cost_codes: list[CostCodeSelectionInput] = strawberry.field(default_factory=list)


@strawberry.input
class CreateGpCustomerAddressInput:
    """Add an address code to an existing GP customer (RM00102) through eConnect's
    taCreateCustomerAddress (#444).

    The create-job dialog picks its job and bill-to addresses out of that customer's existing codes, so
    a job site nobody had entered in GP meant abandoning the dialog, opening GP to add the address, and
    starting over. This is the same record GP's Customer Address Maintenance window creates.

    No company field: the connected relay is enrolled for exactly one GP company, which is the only one
    this could be written to - the same resolution createGpJob uses.

    The four required fields are what makes the row an address anyone could ship hardware to. Server-side
    truth lives in the relay's CreateCustomerAddressRequest, which trims, uppercases the code and bounds
    every value against GP's own char widths (rejecting rather than truncating); these are plain strings
    carrying what the user typed."""

    customer_number: str
    address_code: str
    address1: str
    city: str

    address2: str | None = None
    state: str | None = None
    zip_code: str | None = None
    country: str | None = None


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
    notes: str | None = None
    # #490: the GP cost code, picked per vendor card at request time. Optional - it is only
    # authoritative at register, where RegisterPOInput.cost_code is still validated against the job's
    # live GP list. Captured here so the buyer who knows the code does not have to remember it later.
    cost_code: str | None = None
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
    # Optional since #451: a LOOSE line raised straight off project inventory has no opening to
    # name - shelf stock belongs to the project, not to a door. Schedule-driven lines still send it.
    opening_number: str | None = None
    opening_item_id: strawberry.ID | None = None
    # Door leaf (#335): set on OPENING_ITEM lines from the assembled OpeningItem. Null on LOOSE.
    leaf: int | None = None
    hardware_category: str | None = None
    product_code: str | None = None
    requested_quantity: int = 1


@strawberry.input
class ShippingOutPRDraftInput:
    request_number: str
    items: list[ShippingOutPRDraftItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class ContainerItemInput:
    """One placement in a container (#451). Order in the list IS the stacking order."""

    item_type: PullRequestItemType
    opening_item_id: strawberry.ID | None = None
    opening_number: str | None = None
    leaf: int | None = None
    hardware_category: str = ""
    product_code: str = ""
    quantity: int = 1


@strawberry.input
class SetContainerItemsInput:
    """Rewrite one container's contents to exactly these placements, in this order (#451).

    A batch rather than place / remove / reorder as three calls: a drag-and-drop surface already
    holds the whole list, and saving it in pieces leaves a moment where the stack is in an order
    nobody chose.
    """

    container_id: strawberry.ID
    items: list[ContainerItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class CreateShippingOutRequestInput:
    """Raise a shipping-out request from the Shipping module rather than from Start a Request (#451).

    Same entity, same guards, same reservations - only the composer differs. This one exists because
    the schedule is not the only reason hardware goes to site: the shipping department is asked for
    stock the schedule never accounted for, and before this the only way to send it was to walk back
    through the import wizard.
    """

    project_id: strawberry.ID
    request_number: str
    items: list[ShippingOutPRDraftItemInput] = strawberry.field(default_factory=list)
    # The caller has seen the "this leaf is short" warning and still wants it on the request (#341).
    acknowledge_incomplete_leaves: bool = False


@strawberry.input
class EditShippingOutRequestInput:
    """Rewrite a PENDING request's lines to exactly `items` (#451).

    Full replace, not a diff: the client sends the request it wants rather than the steps to get
    there, so there is no ordering in which it can transiently over-claim. Emptying it is refused -
    reject the request instead.
    """

    id: strawberry.ID
    items: list[ShippingOutPRDraftItemInput] = strawberry.field(default_factory=list)
    acknowledge_incomplete_leaves: bool = False


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
    notes: str | None = None
    # Issue #216: the PM's requested date, captured at request creation.
    preferred_delivery_date: date | None = None
    # Issue #156: optional order-time dollar costs. Null means "not entered"; 0 is a valid value.
    shipping_cost: float | None = None
    tariff_amount: float | None = None
    # #490: optional GP cost code, carried to register as the default. RegisterPOInput.cost_code
    # stays authoritative - a code that has since left the job's GP list is caught there.
    cost_code: str | None = None
    # #481: the vendor's quotation this request is raised against. Usually arrives after the draft
    # exists and is typed on the PO afterwards, but a buyer working from a quote in hand has nowhere
    # to put it at creation without this.
    vendor_quote_number: str | None = None


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
    # The GP vendor picked live from the gpVendors(company) list - the only vendor identity a PO has
    # (#200 dropped the sync'd mirror, #509 the local contact table). Snapshotted onto the PO for
    # display.
    gp_vendor_id: str
    gp_vendor_name: str
    gp_company: str
    # GP buyer (POP00101), picked from the gpBuyers dropdown - always sent so the relay's own
    # per-workstation buyer fallback never decides it for a server-brokered call.
    buyer_id: str
    line_items: list[RegisterPOLineItemInput]
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
class TransferInventoryInput:
    source_type: TransferSourceType
    source_id: strawberry.ID
    quantity: int
    dest_warehouse_id: strawberry.ID
    dest_aisle: str
    dest_row: str
    dest_bay: str


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
    quotation_number: str | None = None
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
    # Empty since #501: a draft is a count, and where the units go is chosen on the Put Away queue
    # after the warehouse manager approves. The field stays because drafts counted before that
    # change still carry their rack rows and the booking still honours them.
    locations: list["LocationInput"] = strawberry.field(default_factory=list)


@strawberry.input
class LocationInput:
    aisle: str
    row: str
    bay: str
    quantity: int
    deficient_quantity: int = 0


@strawberry.input
class CreateReceiveDraftInput:
    """A counted delivery, submitted for a Warehouse Manager to approve.

    The same shape `CreateReceiveInput` had before receives were split in two, minus nothing: what
    the person counting the truck enters did not change, only when it reaches GP. The author is the
    Clerk-authenticated caller (#199/#427), never a client-supplied name.
    """

    po_id: strawberry.ID
    warehouse_id: strawberry.ID | None = None
    line_items: list[ReceiveLineItemInput] = strawberry.field(default_factory=list)
    # #504: the packing slip this count was made against. Required - a count with no paper behind
    # it cannot be checked when it is disputed. Upload it as a PACKING_SLIP PO document first and
    # pass the id here.
    packing_slip_document_id: strawberry.ID | None = None
    # Client-generated, one per submit action and re-sent on retry, so a network timeout that
    # actually committed cannot leave two drafts against one PO.
    idempotency_key: str = ""


@strawberry.input
class UpdateReceiveDraftInput:
    """Rewrite what a draft says was counted - a manager correcting it before approval, or its author
    fixing what a rejection asked them to. Replaces the lines wholesale."""

    draft_id: strawberry.ID
    warehouse_id: strawberry.ID | None = None
    line_items: list[ReceiveLineItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class RejectReceiveDraftInput:
    draft_id: strawberry.ID
    # Required by the resolver, not by the schema: an empty string is a typed error naming the field,
    # which is a better answer than a GraphQL validation failure the dialog cannot attach to an input.
    reason: str = ""


@strawberry.input
class ApproveReceiveDraftInput:
    """Approve a draft, which is what posts the GP receipt and credits inventory.

    Issue #202 #1: the idempotency key (one per user action, re-sent on retry) is what makes a retry
    a no-op in GP rather than a second receipt. It is also the draft's approval claim - a retry
    carrying the same key resumes an approval that died mid-flight instead of conflicting with it."""

    draft_id: strawberry.ID
    idempotency_key: str = ""


@strawberry.input
class DecideReceiveDecisionInput:
    decision_id: strawberry.ID
    decision: ReceiveDecisionChoice


@strawberry.input
class ShipmentItemInput:
    item_type: PullRequestItemType
    opening_item_id: strawberry.ID | None = None
    opening_number: str | None = None
    product_code: str | None = None
    hardware_category: str | None = None
    quantity: int = 1


@strawberry.input
class DeliveryRequestHeaderInput:
    """The Delivery Request header, on both of the mutations that write it (#453).

    A base rather than the same twenty fields typed out under each input. Two paths write this
    header - `confirmShipment` fills it in and `updateShipmentDetails` rewrites it - and a field
    that reached one but not the other is a field the shipping department can set and never
    correct, or correct and never set. Neither breaks the build or any test, so the drift is
    silent until somebody notices a box on the paper that will not stick.

    The names have to match `shipping_repository.DELIVERY_REQUEST_FIELDS` as well as the count:
    that tuple is what reads the header back off either input, so a field named differently here is
    a field the resolver quietly never persists.

    Every field is optional and stays optional. The form is filled in against whatever the site has
    told the shipping department, and a blank on it is a real answer - refusing a shipment because
    nobody knew the gate number would stop hardware leaving over paperwork.

    Not a GraphQL input type of its own: Strawberry flattens these fields into each subclass, so
    the schema shows twenty fields on both inputs and nothing named DeliveryRequestHeaderInput.
    """

    pickup_date: date | None = None
    delivery_date: date | None = None
    shipper_email: str | None = None
    shipper_phone: str | None = None
    pickup_location: str | None = None
    # The name of a ShipmentMethod, snapshotted onto the slip (#451). Sent as a string rather than
    # an id so a shipment keeps printing the method it left under after that method is renamed.
    shipment_method: str | None = None
    carrier_tag_bol: str | None = None
    weight_lbs: float | None = None
    delivery_address: str | None = None
    special_instructions: str | None = None
    gate_number: str | None = None
    forklift_onsite: str | None = None
    material_coming_back: str | None = None
    site_material_included: str | None = None
    construction_temp_keys: str | None = None
    extra_frame_anchors: str | None = None
    contractor_contact_name: str | None = None
    contractor_contact_phone: str | None = None
    ucsh_contact_name: str | None = None
    ucsh_contact_phone: str | None = None
    sales_order_number: str | None = None


@strawberry.input
class ConfirmShipmentInput(DeliveryRequestHeaderInput):
    """What went on the truck, plus the Delivery Request written for it (#447)."""

    project_id: strawberry.ID
    packing_slip_number: str
    items: list[ShipmentItemInput] = strawberry.field(default_factory=list)


@strawberry.input
class ConfirmShipmentFromContainersInput(DeliveryRequestHeaderInput):
    """Ship whole containers as one shipment (#451).

    The container flow's confirm. Same Delivery Request header as `ConfirmShipmentInput` above and
    the same slip at the far end - only where the items come from differs, which is why this carries
    container ids instead of a hand-built item list.
    """

    project_id: strawberry.ID
    packing_slip_number: str
    container_ids: list[strawberry.ID] = strawberry.field(default_factory=list)


@strawberry.input
class UpdateShipmentDetailsInput(DeliveryRequestHeaderInput):
    """Correct the Delivery Request of a shipment that has not been picked up yet (#447).

    **Full replace.** Every header field is applied exactly as given, and a field given as null is
    CLEARED. The client sends all of them on every edit, blanks as explicit nulls, because the
    alternative reading - "absent means leave it alone" - gives a form that can be corrected but
    never emptied, so a phone number typed against the wrong shipment could not be taken back off it.

    Only the paper form is here. The slip number, the project, the items, and who shipped it and when
    are the record of what left the building, and an edit must never be able to rewrite that. The
    backend also refuses the whole call once the shipment is past SCHEDULED, because from then on a
    driver is carrying a printed copy that the stored record has to keep matching.
    """

    id: strawberry.ID


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


@strawberry.input
class InstallReplacementInput:
    """Fit arrived replacement hardware to an already-completed leaf (#341). The quantity can only
    come out of what the replacement pull actually delivered, so this cannot inflate a leaf."""

    shop_assembly_opening_item_id: strawberry.ID
    quantity: int


@strawberry.input
class PickLineInput:
    """One line the warehouse user dictated: this many units of this product off this location (#367).

    The combo is carried alongside the location id rather than derived from it, so the server can
    check the two agree. A client that has drifted from the sheet - a stale location list, a row
    re-keyed to another product - is refused instead of quietly deducting the wrong bin."""

    hardware_category: str
    product_code: str
    inventory_location_id: strawberry.ID
    quantity: int


@strawberry.input
class StagePullOpeningsInput:
    """Confirm that the cart(s) for these openings of an approved shop-assembly pull are built (#343).

    Openings already staged are skipped, not refused, so a double-click or a stale checklist is a
    no-op. Staging the last one completes the pull."""

    pull_request_id: strawberry.ID
    opening_ids: list[strawberry.ID]


@strawberry.input
class CancelPullRequestInput:
    """Cancel an approved pull and return its hardware to inventory (#343).

    All-or-nothing: an opening whose assembly has started or finished blocks the whole cancellation,
    and the refusal names them. `reason` is optional but shown to whoever raised the pull."""

    id: strawberry.ID
    reason: str | None = None


@strawberry.input
class CompleteOpeningInput:
    opening_id: strawberry.ID
    # #498: deprecated and ignored. Completion no longer records a location - the assembler was
    # typing free text with no warehouse choice and no validation, and warehouse staff could not
    # correct it. Kept in the schema until frontends stop sending them (#438 pattern).
    aisle: str | None = None
    row: str | None = None
    bay: str | None = None


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


@strawberry.input
class AdjustStockQuantityInput:
    stock_item_id: strawberry.ID
    new_quantity: int
    reason_text: str


@strawberry.input
class MoveStockLocationInput:
    stock_item_id: strawberry.ID
    new_aisle: str
    new_row: str
    new_bay: str


@strawberry.input
class ReclassifyStockItemInput:
    stock_item_id: strawberry.ID
    new_hardware_category: str
    new_product_code: str
    quantity: int
    reason_text: str | None = None


@strawberry.input
class ReportInventoryDeficiencyInput:
    inventory_location_id: strawberry.ID
    quantity: int
    reason_text: str | None = None


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


@strawberry.input
class ReportStockDeficiencyInput:
    stock_item_id: strawberry.ID
    quantity: int
    reason_text: str | None = None


@strawberry.input
class ReportDeficiencyAtAssemblyInput:
    shop_assembly_opening_item_id: strawberry.ID
    quantity: int
    reason_text: str | None = None


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
