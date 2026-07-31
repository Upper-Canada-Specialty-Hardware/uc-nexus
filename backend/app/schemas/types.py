from datetime import date, datetime

import strawberry

from .enums import (
    AssemblyStatus,
    AuditAction,
    AuditEntityType,
    Classification,
    DeficiencyResolution,
    DeficientItemSource,
    GpOutboxStatus,
    HardwareItemState,
    LeafStatus,
    NotificationType,
    OpeningItemState,
    PickOutcome,
    PipelineStage,
    PODocumentType,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReconciliationStatus,
    ReturnDisposition,
    ShippingOutRequestStatus,
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
    # Door-leaf count (#311): 1 (single) or 2 (pair). The "N of M leaves shipped" denominator.
    leaf_count: int | None
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
    # Door leaf this item belongs to (#311): 1 or 2, or null for frames.
    leaf: int | None
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
    # Stamped when an admin-armed adopt window rebound this install's credential (#353 PR B). Kept on
    # the row (and shown in the grid) because adoption accepts a connection that could not otherwise
    # authenticate - that has to stay visible long after the in-memory window is gone.
    adopted_at: datetime | None = None
    adopted_by: str | None = None
    # SHA-256 hex of this install's Bearer secret - the value RELAY_SEED_SECRET_HASH wants (#414).
    # Exposed so an admin can copy it into the Railway PR-environment template instead of running SQL
    # against Postgres. A digest is a verifier, not a credential: it authenticates nothing, only its
    # preimage does, and that never leaves the workstation. The query is admin-gated regardless.
    secret_hash: str | None = None


@strawberry.type
class RelayAdoptWindow:
    """An open "adopt the next relay connection" window. While one is armed, the first /relay-link
    handshake presenting ANY secret is bound to this install."""

    install_id: strawberry.ID
    label: str
    expires_at: datetime
    armed_by: str


@strawberry.type
class RelayStatus:
    connected: bool
    # The GP company the connected relay is enrolled for (null when disconnected). The PO/receive/adopt
    # dialogs drive their company selection from this so they never offer a company the live relay can't
    # serve - a mismatch would fail every gp_* read and reject a submit as RelayUnavailable (issue #202 #6).
    company: str | None = None
    # The connected relay's build tag from its hello frame (issue #315), e.g. 'relay-v0.1.0-build.30'.
    # Null when disconnected, or when an older relay that predates the hello frame is connected. Shown on
    # the Admin -> Relay Installs page so an out-of-date relay is visible before an op fails.
    build: str | None = None
    # Which relay_installs row is holding the live connection (#366). The Relay Installs grid used to
    # infer this from company + last_seen_at; now it can say so outright, and it is what disables Remove
    # on the connected row.
    install_id: strawberry.ID | None = None


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
    # GP CURNCYID (issue #257: the vendor dictates the PO currency). Blank in GP -> 'CAD'. Shown
    # read-only on the register-PO form; USD vendors have no tax-detail dropdown.
    currency: str


@strawberry.type
class GpBuyer:
    """A registered GP buyer (POP00101) read live via the relay, for the admin screens that link a
    Nexus account to a GP buyer identity (#409).

    The description is the whole reason this exists alongside `gpBuyers`, which returns bare ids for
    the Create PO dropdown: an id like 'donr' or 'mira' says nothing about who it is, and an admin
    picking the wrong one silently mis-attributes every PO that account goes on to create."""

    buyer_id: str
    description: str | None


@strawberry.type
class GpCostCode:
    cost_code: str  # two-segment number 'cc1-cc2' e.g. '310-000'
    description: str | None
    cost_element: int


@strawberry.type
class GpCostCodeMasterEntry:
    """One code from GP's cost code MASTER (JC40202), for the create-job cost-code picker (#448).

    Not GpCostCode above, which is a code already on a job (JC00701). This is the catalogue those rows
    are provisioned from, so it carries the one thing the per-job read has no use for: whether the
    division the job is being created under actually has a GL account for this code's cost element.

    `mapped` false means it does not - either JC40302 has no row for that (division, cost element), or
    the row it has points at an account index that is not in GL00105. The second case is the stale
    sandbox defence: a dangling index is exactly what #425 quarantines a job for, so provisioning a
    code with one would create the broken job this picker exists to prevent."""

    cost_code: str  # two-segment number 'cc1-cc2' e.g. '210-200'
    description: str | None
    cost_element: int
    mapped: bool


@strawberry.type
class GpCustomer:
    """A GP customer (RM00101) read live via the relay, for the create-job customer picker (#380)."""

    customer_number: str
    customer_name: str | None


@strawberry.type
class GpEmployee:
    """A GP payroll employee (UPR00100) read live via the relay, for the create-job estimator and
    WS manager pickers (#392). The job proc validates both against this master, so these cannot be
    free text - a value that isn't here is rejected with "The estimator does not exist in the payroll
    master table"."""

    employee_id: str
    first_name: str | None
    last_name: str | None


@strawberry.type
class GpCustomerAddress:
    """One address code on a GP customer (RM00102), for the create-job job/bill-to address pickers
    (#380). Scoped to a single customer: the job proc validates an address code against that
    customer's addresses, so a code belonging to another customer is not a valid choice here.

    The display fields exist because an address code on its own ('MAIN', 'PRIMARY', 'RIH') says
    nothing about which site it is."""

    address_code: str
    address1: str | None
    city: str | None
    state: str | None


@strawberry.type
class GpTaxSchedule:
    """A GP tax SCHEDULE (TX00101) read live via the relay, for the create-job tax-schedule and
    use-tax-schedule pickers (#380). Distinct from GpTaxDetail, which is a TX00201 tax detail:
    a schedule groups details, and the job proc takes the schedule."""

    tax_schedule_id: str
    description: str | None


@strawberry.type
class CreateGpJobResult:
    """The outcome of createGpJob (#392).

    `created` distinguishes the two ways this mutation succeeds. Normally GP creates the job and
    `created` is true. But when GP already holds that job number the mutation adopts it instead of
    dead-ending (the retry-after-ambiguous-failure path), and the caller has to be able to tell -
    otherwise the UI reports a creation that never happened.

    `cost_codes_provisioned` is how many JC00701 rows GP really ended up with, read back by the relay
    rather than counted from the request (#448). It exists because a relay older than #448 ignores the
    unknown `cost_codes` key and creates the bare, quarantined job this feature exists to prevent -
    silently, and with an otherwise perfectly successful reply. A zero against a non-empty selection is
    the only signal of that, so the dialog can say the codes did not land instead of claiming they did."""

    project: "Project"
    created: bool
    cost_codes_provisioned: int


@strawberry.type
class GpJobSyncResult:
    """What one pass of the GP job sync did (#380). `total` is every job the relay reported;
    `adopted` is how many of those did not yet exist as projects and were created."""

    total: int
    adopted: int


@strawberry.type
class GpTaxDetail:
    """A GP purchase tax detail (TX00201, TXDTLTYP=2) read live via the relay, for the register-PO
    tax-detail dropdown (issue #257). GP-first: the options are whatever the company defines
    (e.g. BC HST P / ON HST - P / PST 7% in production)."""

    tax_detail_id: str
    description: str | None
    percent: float


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
class POOpeningItem:
    hardware_category: str
    product_code: str
    quantity: int


@strawberry.type
class POOpening:
    """One (opening, leaf) this PO's hardware was bought for (#302). The PO carries only fungible
    (category, product) lines, so this is the only place the buyer can see which doors the order is
    for. leaf is null for a frame or a legacy item that predates #311."""

    opening_number: str
    leaf: int | None
    building: str | None
    floor: str | None
    location: str | None
    items: list[POOpeningItem]


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
    preferred_delivery_date: date | None
    expected_delivery_date: date | None
    ordered_at: datetime | None
    created_at: datetime
    updated_at: datetime
    line_items: list[POLineItem]
    receive_records: list[ReceiveRecord]
    documents: list[PODocumentInfo]
    document_data: PODocumentData | None = None


@strawberry.type
class GpSetupIssue:
    """One JC00701 cost code on this project's GP job whose GL account index does not exist in the
    company's chart (#425). What the quarantine banner names, so the message points at something
    accounting can look up rather than at "GP setup"."""

    cost_code: str  # 'phase-step-element', as the register-PO dropdown shows it
    account_index: int  # the dangling index, absent from GL00105


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
    # GP job setup verdict (#425). Plain scalar columns on the project row plus a parse of the JSON
    # detail column, so no relationship is walked and these are safe on the all-projects list query -
    # unlike `openings` below, which list callers deliberately leave empty.
    #
    # null means never checked (no relay has answered yet) and does NOT quarantine; false does. The
    # frontend must treat them differently or a relay outage would grey out the whole application.
    gp_setup_ok: bool | None
    gp_setup_checked_at: datetime | None
    gp_setup_issues: list[GpSetupIssue]
    openings: list[Opening]
    purchase_orders: list[PurchaseOrder]


@strawberry.type
class ProjectScheduleHardwareItem:
    opening_number: str
    product_code: str
    material_id: str
    # Door leaf this item belongs to (#311): 1 or 2, or null for frames.
    leaf: int | None
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
    # Door leaf this assembled unit is (#311): 1 or 2, or null (legacy whole-opening unit).
    leaf: int | None
    # The opening's total door-leaf count (#311), the "N of M leaves shipped" denominator. Only
    # populated by the openingItems list resolver; null elsewhere.
    leaf_count: int | None
    quantity: int
    assembly_completed_at: datetime
    state: OpeningItemState
    aisle: str | None
    row: str | None
    bay: str | None
    created_at: datetime
    updated_at: datetime
    installed_hardware: list[OpeningItemHardware]
    # Units this leaf is still owed (#341): condemned-and-unreplaced plus arrived-but-not-fitted,
    # summed from its source shop-assembly checklist lines. > 0 means the leaf is physically short of
    # what its hardware list claims, so the shipping wizard flags it and shipping it takes an explicit
    # acknowledgment. Only populated by the resolvers that ask for it (the openingItems list and the
    # detail view); null everywhere else, which reads as "not evaluated", not as "nothing owed".
    awaiting_replacement_quantity: int | None = None
    # Units this leaf was owed by the schedule that its request never pulled - they were not
    # available to claim when it was sent, so nothing arrived and nothing is in flight. The other
    # half of the same shipping decision as the field above, and deliberately separate: waiting fixes
    # an awaiting-replacement unit and does nothing at all for one of these. Same null-means-not-
    # evaluated convention.
    never_pulled_quantity: int | None = None


@strawberry.type
class PullRequestItem:
    id: strawberry.ID
    pull_request_id: strawberry.ID
    item_type: PullRequestItemType
    opening_number: str
    opening_item_id: strawberry.ID | None
    # Deficient shop-assembly checklist item this line replaces (#339). Set only on PR-REPL lines.
    sa_opening_item_id: strawberry.ID | None
    # Door leaf this pull line is for (#311): 1 or 2, or null (legacy / leaf-agnostic).
    leaf: int | None
    hardware_category: str | None
    product_code: str | None
    requested_quantity: int
    # Fetch check-off on an OPENING_ITEM line (#367): the assembled leaf has been collected off the
    # rack. Always null on a LOOSE line, which is picked by quantity instead.
    fetched_at: datetime | None = None
    fetched_by: str | None = None


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
    # Who cancelled the pull and why (#343). Null unless status is CANCELLED.
    cancelled_by: str | None = None
    cancellation_reason: str | None = None
    # Per-opening staging progress, DERIVED, never stored (#343). NOT_PULLED / PARTIAL / PULLED read
    # over the pull's shop-assembly openings - PARTIAL being "some carts built, some not", which is
    # a statement about the set and so has no place on any single opening's own pull_status.
    #
    # Null means staging does not apply *or* was not evaluated: a shipping-out pull, a PR-REPL
    # replacement pull, and a legacy pull all have no openings, and the resolvers that do not compute
    # the rollup leave it null rather than implying "nothing staged". Populated by pullRequests,
    # pullRequestDetails, and the staging/approve/complete/cancel mutation results.
    staging_status: PullStatus | None = None
    staged_opening_count: int | None = None
    total_opening_count: int | None = None
    # When the pick was confirmed and by whom (#367). This is the moment stock left inventory;
    # `approvedAt` only says the warehouse started on the pull. Staging and completion gate on this.
    picked_at: datetime | None = None
    picked_by: str | None = None
    # Stock has come off the shelf for this pull but it is not fully picked - a short confirm waiting
    # on a second one. Only computed for un-picked pulls (it is meaningless once `pickedAt` is set);
    # null means "not evaluated", never "nothing picked".
    partially_picked: bool | None = None


@strawberry.type
class ShopAssemblyOpeningItem:
    id: strawberry.ID
    shop_assembly_opening_id: strawberry.ID
    hardware_category: str
    product_code: str
    # Owed: what the hardware schedule says this door leaf takes.
    quantity: int
    # What the requester actually claimed out of available inventory when the request was sent, and
    # therefore what physically arrives on the cart. Short is `quantity - allocatedQuantity`, derived
    # on the client exactly as it is on the server - it is never stored, because the authority on
    # what a leaf is still missing is the current schedule against what is on the leaf, not this
    # request's record of what it managed to send.
    allocated_quantity: int = 0
    # Persisted assembly progress (#340). installed_quantity is what the assembler has recorded
    # fitting to the leaf; deficient_quantity is what has already been condemned and replaced.
    # Remaining is allocated - installed - deficient, derived on the client - completion is refused
    # while any line still has remaining > 0. Short units are outside that sum: they were never
    # pulled, so there is nothing on the bench to disposition.
    installed_quantity: int = 0
    deficient_quantity: int = 0
    # Units whose replacement has arrived but is not on the leaf yet (#341). Non-zero only on a
    # COMPLETED opening - before completion an arrived replacement just goes back to being remaining
    # work. installed + deficient + replacement_pending never exceeds quantity.
    replacement_pending_quantity: int = 0


@strawberry.type
class ReplacementWorkItem:
    """One outstanding replacement install on an already-completed door leaf (#341).

    Deliberately not a ShopAssemblyOpening: the opening is COMPLETED and stays that way, so this
    cannot ride in myWork's normal list without either lying about the leaf's status or reopening a
    finished work unit. It is the narrower unit "fit these N units of this product to a leaf that is
    otherwise done", assigned to whoever last held the leaf.

    opening_item_state is SHIPPED_OUT when the replacement arrived after the leaf left the building.
    Those rows are listed on purpose - the hardware is real and must not be silently stranded - but
    installReplacement refuses them; they belong to reallocation.
    """

    shop_assembly_opening_item_id: strawberry.ID
    shop_assembly_opening_id: strawberry.ID
    project_id: strawberry.ID
    opening_number: str
    leaf: int | None
    building: str | None
    floor: str | None
    hardware_category: str
    product_code: str
    pending_quantity: int
    assigned_to_user_id: str | None
    assigned_to: str | None
    opening_item_id: strawberry.ID | None
    opening_item_state: OpeningItemState | None


@strawberry.type
class ShopAssemblyOpening:
    id: strawberry.ID
    # Legacy SAR parent (nullable since #222); openings now hang off pull_request_id.
    shop_assembly_request_id: strawberry.ID | None
    pull_request_id: strawberry.ID | None
    opening_id: strawberry.ID
    pull_status: PullStatus
    # Stable Clerk user id the opening is claimed by (#324); assigned_to is the display name.
    assigned_to_user_id: str | None
    assigned_to: str | None
    assembly_status: AssemblyStatus
    completed_at: datetime | None
    items: list[ShopAssemblyOpeningItem]
    # Door leaf this assembly work unit is for (#311): 1 or 2, or null (legacy whole-opening).
    leaf: int | None = None
    # Resolved from Opening table (populated by myWork and assembleList queries)
    opening_number: str | None = None
    building: str | None = None
    floor: str | None = None
    # When this opening's cart was confirmed staged, and by whom (#343). Null while NOT_PULLED, and
    # on openings staged before per-opening staging existed (they were staged wholesale).
    staged_at: datetime | None = None
    staged_by: str | None = None


@strawberry.type
class PipelineOpening:
    """Where one door leaf is in shop assembly, and what it is still owed (#344).

    Every field is derived from state slices 1-5 already persist; nothing here is stored. The raw
    facts sit next to the derived `stage` on purpose - a screen that wants to phrase the journey
    differently should not have to reverse-engineer the ladder.
    """

    shop_assembly_opening_id: strawberry.ID
    opening_number: str
    leaf: int | None
    building: str | None
    floor: str | None
    location: str | None
    stage: PipelineStage
    pull_status: PullStatus
    staged_at: datetime | None
    staged_by: str | None
    assigned_to_user_id: str | None
    assigned_to: str | None
    assembly_status: AssemblyStatus
    completed_at: datetime | None
    # Owed by the schedule vs what the request could claim. The progress counters below partition
    # `allocated_unit_count`; `short_unit_count` is the rest and was never pulled.
    planned_unit_count: int
    allocated_unit_count: int
    short_unit_count: int
    installed_unit_count: int
    deficient_unit_count: int
    replacement_pending_unit_count: int
    # Units still owed to this leaf: condemned-and-unreplaced plus arrived-but-not-fitted (#341).
    awaiting_replacement_unit_count: int
    # Replacement hardware is sitting for a leaf that has already left the building (#341).
    # installReplacement refuses it; it belongs to reallocation.
    replacement_arrived_after_ship: bool
    opening_item_id: strawberry.ID | None
    opening_item_state: OpeningItemState | None
    # Where the assembled leaf physically is - the "completed (location)" rung.
    assembled_location: str | None


@strawberry.type
class AssemblyPipelineSummary:
    """One shop-assembly request's journey in counts (#344).

    Listable at All-Projects scale: every count comes from a grouped aggregate over the whole result
    set, so the resolver's statement count is fixed however many requests come back.
    """

    request_id: strawberry.ID
    request_number: str
    project_id: strawberry.ID
    # Which project, without a second lookup, for the All-Projects view: project_code is the human
    # job number and project_name its description.
    project_code: str | None
    project_name: str | None
    request_status: ShopAssemblyRequestStatus
    created_by: str
    created_at: datetime
    accepted_by: str | None
    accepted_at: datetime | None
    rejected_by: str | None
    rejected_at: datetime | None
    # The same #342 note the accept screen shows as an amber alert.
    integrity_note: str | None
    # The live pull, never a cancelled one (#343 made request_number unique among live pulls only).
    pull_request_id: strawberry.ID | None
    pull_request_status: PullRequestStatus | None
    pull_approved_at: datetime | None
    pull_completed_at: datetime | None
    # Derived staging rollup - the same reading PullRequest.stagingStatus gives (#343). Null when the
    # request has no openings, which reads as "not applicable", never "nothing staged".
    staging_status: PullStatus | None
    # Cancellation history (#343): a cancelled pull keeps its number and hands its openings back to a
    # PENDING request, so without this the request would read as never having been accepted.
    cancelled_pull_count: int
    last_cancelled_at: datetime | None
    last_cancelled_by: str | None
    last_cancellation_reason: str | None
    opening_count: int
    staged_opening_count: int
    assigned_opening_count: int
    in_progress_opening_count: int
    completed_opening_count: int
    shipped_opening_count: int
    planned_unit_count: int
    # Sent short: a request can be legitimately complete and still not have delivered its full bill
    # of hardware, and nothing else on this row would say so.
    allocated_unit_count: int
    short_unit_count: int
    installed_unit_count: int
    deficient_unit_count: int
    replacement_pending_unit_count: int
    awaiting_replacement_opening_count: int
    replacement_after_ship_opening_count: int
    short_opening_count: int
    # The stage of the least-advanced opening: what the request is waiting on, not its best news.
    stage: PipelineStage


@strawberry.type
class AssemblyPipeline:
    """A request's summary plus a row per door leaf (#344) - the detail view."""

    summary: AssemblyPipelineSummary
    openings: list[PipelineOpening]


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
    # Something happened to this request after it was created that the acceptor has to know about
    # (#342): a schedule re-upload landed under it, or the reservations backfill could not cover it.
    # Null means nothing has.
    integrity_note: str | None
    openings: list[ShopAssemblyOpening]


@strawberry.type
class ShippingOutRequestItem:
    id: strawberry.ID
    shipping_out_request_id: strawberry.ID
    item_type: PullRequestItemType
    opening_number: str
    opening_item_id: strawberry.ID | None
    # Door leaf this request line is for (#335): 1 or 2 on an OPENING_ITEM line, null on LOOSE.
    leaf: int | None
    hardware_category: str | None
    product_code: str | None
    requested_quantity: int


@strawberry.type
class ShippingOutRequest:
    id: strawberry.ID
    request_number: str
    project_id: strawberry.ID
    status: ShippingOutRequestStatus
    created_by: str
    approved_by: str | None
    rejected_by: str | None
    rejection_reason: str | None
    created_at: datetime
    approved_at: datetime | None
    rejected_at: datetime | None
    # See ShopAssemblyRequest.integrity_note (#342).
    integrity_note: str | None
    pull_request_id: strawberry.ID | None
    items: list[ShippingOutRequestItem]


@strawberry.type
class PackingSlipItem:
    id: strawberry.ID
    packing_slip_id: strawberry.ID
    item_type: PullRequestItemType
    opening_item_id: strawberry.ID | None
    opening_number: str | None
    # Door leaf this shipped line was for (#311): 1 or 2, or null (loose / legacy).
    leaf: int | None
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
    # #293: Start a Task now mints request entities (PENDING), not PullRequests. A signed-in user
    # accepts them downstream, which mints the warehouse PullRequest.
    shipping_out_requests: list[ShippingOutRequest]
    shop_assembly_request: ShopAssemblyRequest | None


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
    # Issue #229: net of deficient units (quantity - deficient_quantity) - the approve gate's basis.
    total_available_quantity: int
    total_value: float


@strawberry.type
class InventoryHierarchyNode:
    hardware_category: str
    product_codes: list[ProductCodeNode]
    total_quantity: int
    total_available_quantity: int
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
    gate (#224): requested vs available, and the gap.

    Since #342 `available` is net of other requests' reservations as well as deficient units, so a
    zero can mean "the stock is here but claimed". `reserved` carries that separately - it is the
    difference between "order more" and "release or refine another request"."""

    hardware_category: str
    product_code: str
    requested: int
    available: int
    short: int
    reserved: int = 0


@strawberry.type
class InventoryAvailability:
    """What one (hardware_category, product_code) in a project can still be claimed for (#342).

    `available = on_hand - deficient - reserved`, floored at 0 - the exact number the Start-a-Task
    creation gate applies, so the wizard can block an over-selection before submission instead of
    letting the user find out from a rejected finalize. Note this is deliberately NOT the same as
    the warehouse inventory view's "available", which is on-hand minus deficient: that view answers
    "what is physically unspoken-for in the building", this one answers "what may I claim".
    """

    hardware_category: str
    product_code: str
    on_hand_quantity: int
    deficient_quantity: int
    reserved_quantity: int
    available_quantity: int


@strawberry.type
class PickSheetLeaf:
    """One door leaf a pick section's units are owed to (#367).

    Every leaf is listed, never summarised into "and N more": the picker is building carts per leaf,
    so the list of leaves *is* the work, and a truncated one sends them back to another screen."""

    opening_number: str
    leaf: int | None
    quantity: int


@strawberry.type
class PickSheetLocation:
    """One inventory row a pick section's product can be taken from (#367).

    `receivedAt` is here so the picker can rotate stock themselves. There is deliberately no
    suggested quantity anywhere in this type: a system suggestion is a default in everything but
    name, and #367 exists because the person at the rack should be the one deciding."""

    inventory_location_id: strawberry.ID
    warehouse_id: strawberry.ID | None
    warehouse_code: str | None
    aisle: str | None
    row: str | None
    bay: str | None
    # On-hand minus condemned: the ceiling `confirmPick` enforces for this row.
    available: int
    received_at: datetime
    # What the saved draft has against this row, and what has already been confirmed off it.
    draft_quantity: int
    applied_quantity: int


@strawberry.type
class PickSheetSection:
    """One product code to pick, with every leaf it is owed to and everywhere it can come from."""

    hardware_category: str
    product_code: str
    required_quantity: int
    applied_quantity: int
    remaining_quantity: int
    # What this pull may actually take: on-hand minus condemned minus *other* requests' claims. The
    # third ceiling `confirmPick` enforces, surfaced so contention shows up on the screen and the
    # printed sheet rather than as a refusal after the picker has walked the racks.
    claimable_quantity: int
    # How far short of `remainingQuantity` that leaves this pull. Zero in the ordinary case.
    claimable_shortfall: int
    leaves: list[PickSheetLeaf]
    locations: list[PickSheetLocation]


@strawberry.type
class PickSheetFetchItem:
    """One assembled leaf to collect off the rack (#367).

    An OPENING_ITEM line moves a leaf whose hardware left fungible inventory at assembly, so nothing
    is deducted for it - it is walked to and picked up. The check-off is persisted so it survives a
    reload or a shift change."""

    pull_request_item_id: strawberry.ID
    opening_item_id: strawberry.ID | None
    opening_number: str
    leaf: int | None
    aisle: str | None
    row: str | None
    bay: str | None
    state: OpeningItemState | None
    fetched_at: datetime | None
    fetched_by: str | None


@strawberry.type
class PickSheet:
    """Everything the pick screen and the printed sheet render from (#367)."""

    pull_request: PullRequest
    sections: list[PickSheetSection]
    fetch_items: list[PickSheetFetchItem]


@strawberry.type
class ConfirmPickResult:
    """What one pick confirmation did (#367).

    SHORT is a resumable state, not a failure: what was entered is deducted and recorded, the pull
    stays In Progress and un-picked, purchasing is notified once, and a later confirmation covers the
    remainder."""

    pull_request: PullRequest
    outcome: PickOutcome
    notification: Notification | None = None
    # Populated when outcome is SHORT: what each combo is still owed, and what is left in the project
    # for it. Empty on PICKED.
    shortfalls: list[InventoryShortfall] = strawberry.field(default_factory=list)
    # Units this confirmation took off the shelf. Zero on a pure fetch pull.
    applied_quantity: int = 0


@strawberry.type
class StagePullOpeningsResult:
    """What one staging confirmation did (#343).

    `openings` comes back so the checklist can re-render from the server's answer rather than an
    optimistic guess, and `completed` says whether this confirmation was the one that finished the
    pull - the client shows a different message for "3 of 8 staged" and "pull complete"."""

    pull_request: PullRequest
    openings: list[ShopAssemblyOpening]
    # Ids staged by *this* call. An opening already staged is skipped, not refused, so this is how a
    # caller tells a real confirmation from a replayed one.
    newly_staged_opening_ids: list[strawberry.ID]
    completed: bool


@strawberry.type
class RestockedLine:
    hardware_category: str
    product_code: str
    quantity: int


@strawberry.type
class CancelPullRequestResult:
    """What a cancellation put back and where the source request ended up (#343)."""

    pull_request: PullRequest
    # The inverse inventory write, per combo. Empty for a pull with no LOOSE lines.
    restocked: list[RestockedLine]
    released_opening_ids: list[strawberry.ID]
    # The source request went back to PENDING for re-acceptance. False for a PR-REPL replacement
    # pull or a legacy pull, which have no source request at all.
    source_request_returned_to_pending: bool
    # The returned hardware was re-claimed for that request. False when it holds no claim - either
    # because there is no source request, or because the re-check came up short, in which case
    # integrityNote says so and the request carries the same message.
    reservations_recreated: bool
    integrity_note: str | None = None


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
class OpeningLeafState:
    """One door leaf's status in the per-opening leaf-status rollup (#313)."""

    leaf: int
    status: LeafStatus


@strawberry.type
class OpeningLeafStatus:
    """Per-opening door-leaf rollup (#313): every leaf 1..leaf_count and its status. project_id /
    project_name are carried so the global (no-projectId) shop-assembly view disambiguates opening
    numbers that collide across projects."""

    project_id: strawberry.ID
    project_name: str
    opening_number: str
    leaf_count: int
    leaves: list[OpeningLeafState]


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
    row: str | None
    bay: str | None


@strawberry.type
class LocationDuplicateGroup:
    canonical_aisle: str | None
    canonical_row: str | None
    canonical_bay: str | None
    variants: list[LocationVariant]


@strawberry.type
class LocationDistinctValues:
    aisles: list[str]
    rows: list[str]
    bays: list[str]


@strawberry.type
class LocationMergeResult:
    inventory_locations: int
    opening_items: int
    stock_items: int


@strawberry.type
class BackOrderedItem:
    # The PO line this row IS. A back-ordered row has no identity of its own, so without this the
    # only key a client can build is its position in the result, which changes under the query's own
    # ORDER BY every time anything is received.
    po_line_item_id: strawberry.ID
    hardware_category: str
    product_code: str
    ordered_quantity: int
    received_quantity: int
    outstanding_quantity: int
    po_number: str | None
    vendor_name: str | None
    expected_delivery_date: date | None
    # None for a stock PO, which has no project to name.
    project_name: str | None


@strawberry.type
class WarehouseDashboard:
    total_item_count: int
    total_value: float
    unlocated_count: int
    pending_pull_shop: int
    pending_pull_shipping: int
    received_last_7_days: int
    back_ordered_count: int
    deficient_count: int


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
    row: str | None
    bay: str | None
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
    row: str | None
    bay: str | None


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
    # Issue #216: the GP BUYERID this account acts as (Clerk publicMetadata.gpBuyerId), or null.
    gp_buyer_id: str | None
    image_url: str


@strawberry.type
class BuyerAssignmentProject:
    """Slim project ref for buyer assignments (the full Project type carries openings)."""

    id: strawberry.ID
    project_id: str
    description: str | None


@strawberry.type
class BuyerAssignment:
    """Issue #216: the projects a GP buyer may create POs for."""

    buyer_id: str
    projects: list[BuyerAssignmentProject]


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


# --- GP write outbox (#353 PR E) ----------------------------------------------------------------------


@strawberry.type
class GpOutboxEntry:
    """One queued GP write, for the admin queue and the pending chips on the PO lists."""

    id: strawberry.ID
    label: str
    op: str
    company: str
    status: GpOutboxStatus
    attempts: int
    next_attempt_at: datetime
    created_at: datetime
    # Which PO this write is against, as `po:<uuid>` - the lists join on it client-side rather than
    # exposing a per-row field on PurchaseOrder, which would be an N+1 on the All-Projects list.
    entity_key: str
    last_error: str | None = None
    failure_kind: str | None = None


@strawberry.type
class GpOutboxSummary:
    """Counts for the queue chip. Scalar aggregates only - this is polled by every open browser."""

    pending: int
    in_flight: int
    failed: int
    oldest_pending_at: datetime | None = None
    # The most recent successful drain. The browser watches this to know a background drain changed
    # data underneath whatever route it happens to be on.
    last_drained_at: datetime | None = None


@strawberry.type
class RegisterPOResult:
    """#353 PR E: registering a PO can now be ACCEPTED without reaching GP.

    `queued` true means the relay was unreachable and the write is on the outbox; the returned PO is
    still DRAFT and will advance itself when the queue drains. False is the old behaviour verbatim."""

    queued: bool
    purchase_order: PurchaseOrder
    outbox_entry_id: strawberry.ID | None = None


@strawberry.type
class CreateReceiveResult:
    """#353 PR E. `receiveRecord` is null when `queued` - the UC Nexus receive is persisted with the
    GP write, so nothing is in inventory yet."""

    queued: bool
    receive_record: ReceiveRecord | None = None
    outbox_entry_id: strawberry.ID | None = None
