from datetime import date, datetime

import strawberry

from .enums import (
    AuditAction,
    AuditEntityType,
    Classification,
    DeficiencyResolution,
    DeficientItemSource,
    GpOutboxStatus,
    HardwareItemState,
    NotificationType,
    PickOutcome,
    PODocumentType,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ReceiveDecisionChoice,
    ReceiveDecisionStatus,
    ReceiveDraftStatus,
    ReconciliationStatus,
    RequestStage,
    ReturnDisposition,
    ShipmentContainerType,
    ShipmentStatus,
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
    # GP's identifiers for the receipt this receive posted (#447). Null on rows created before the
    # columns existed, and on the rare receive whose relay response carried no number.
    receipt_number: str | None
    batch_number: str | None
    created_at: datetime
    line_items: list[ReceiveLineItem]


@strawberry.type
class RecentReceiveRecord:
    receive_record: ReceiveRecord
    po_number: str | None
    total_items_received: int


@strawberry.type
class ReceiveDraftLocation:
    aisle: str
    row: str
    bay: str
    quantity: int
    deficient_quantity: int


@strawberry.type
class ReceiveDraftLineItem:
    id: strawberry.ID
    po_line_item_id: strawberry.ID
    hardware_category: str
    product_code: str
    quantity_received: int
    locations: list[ReceiveDraftLocation]


@strawberry.type
class ReceiveDraft:
    """A counted delivery waiting on a Warehouse Manager. Nothing here has reached GP.

    `poNumber` and `projectId` are denormalized off the PO because every consumer - the approvals
    queue, the author's own list, the PO row's pending chip - renders them beside the draft, and
    resolving them through a relationship would be one SELECT per row.

    `createdBy` is the person who counted the hardware and whose name lands on the ReceiveRecord at
    approval; `reviewedBy` is whoever approved or rejected it. `receiveRecordId` null on an APPROVED
    draft is not a contradiction: the relay was down, the receipt is on the GP outbox, and the record
    appears when it drains.
    """

    id: strawberry.ID
    status: ReceiveDraftStatus
    po_id: strawberry.ID
    po_number: str | None
    project_id: strawberry.ID | None
    warehouse_id: strawberry.ID | None
    # #499: what the PO's creator said to do with this delivery. SHIP_OUT means the approval belongs
    # to the shipping request rather than the warehouse manager's queue. Null when nobody was asked
    # (a stock PO) or when the draft predates the question being raised at count time.
    keep_or_ship_decision: ReceiveDecisionChoice | None = None
    # The question was raised and is still unanswered. A manager must still be able to approve one -
    # a creator on holiday cannot be allowed to strand a counted truck - and approving it means
    # keeping it, so the row says the answer is outstanding rather than hiding it.
    decision_pending: bool = False
    created_by_user_id: str
    created_by: str
    reviewed_by: str | None
    reviewed_at: datetime | None
    rejection_reason: str | None
    # The key an in-flight approval is holding this draft under. Exposed so a reviewer whose approval
    # died ambiguously (a dispatched disconnect, a timeout - GP may hold the receipt) can retry with
    # the SAME key and resume through the idempotency ledger. Without it the key lives only in the
    # browser tab that started the approval, and a reload would strand the draft in APPROVING.
    approval_idempotency_key: str | None
    receive_record_id: strawberry.ID | None
    outbox_entry_id: strawberry.ID | None
    # #504: the packing slip this count was made against. Null only on drafts raised before the
    # requirement existed, which render as "created before the requirement" rather than as missing.
    packing_slip_document_id: strawberry.ID | None
    total_quantity: int
    created_at: datetime
    updated_at: datetime
    line_items: list[ReceiveDraftLineItem]


@strawberry.type
class ReceiveDecisionLine:
    hardware_category: str
    product_code: str
    quantity_received: int


@strawberry.type
class ReceiveDecision:
    """The keep-or-ship question a landed shipment raises for whoever ordered it.

    Raised when the count is submitted since #499, so exactly one of the two ids below is set: a
    draft-stage question names the count, and gets its receive record stamped on when the warehouse
    manager's approval books the receipt.
    """

    id: strawberry.ID
    status: ReceiveDecisionStatus
    decision: ReceiveDecisionChoice | None
    po_id: strawberry.ID
    po_number: str | None
    project_id: strawberry.ID
    receive_record_id: strawberry.ID | None
    receive_draft_id: strawberry.ID | None
    # Null before the approval books the receipt, and null while one is queued on the GP outbox -
    # either way GP has not numbered it yet.
    receipt_number: str | None
    # At draft stage these are when the count was submitted and who counted it; once booked they are
    # the receipt's. Same question, same card, whichever stage it is at.
    received_at: datetime
    received_by: str
    created_at: datetime
    decided_at: datetime | None
    line_items: list[ReceiveDecisionLine]


@strawberry.type
class ReceivingHistoryPO:
    """One row of the Receiving History list (#447): a GP-registered PO and how much of it landed.

    Scalars only, deliberately. The row expands to its individual receives through the existing
    `poReceivingDetails` query, fetched when the user opens it - so the list itself never carries a
    child collection, and a cross-project history of every PO in the database stays one query.
    """

    id: strawberry.ID
    po_number: str | None
    request_number: str
    status: POStatus
    vendor_name: str | None
    project_id: strawberry.ID | None
    ordered_total: int
    received_total: int
    receive_count: int
    last_received_at: datetime | None


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
    quotation_number: str | None
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
    # Clerk user id of whoever raised this PO request. Null on POs from before it was recorded.
    created_by_user_id: str | None
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
    # Persisted SITE_HARDWARE / SHOP_HARDWARE, or null for an item never classified (#492). The
    # wizard reads it to restore Site/Shop when a re-import resumes from the last uploaded schedule.
    classification: Classification | None


@strawberry.type
class ProjectHardwareSchedule:
    project: Project
    openings: list[Opening]
    hardware_items: list[ProjectScheduleHardwareItem]


@strawberry.type
class ProjectOpeningRow:
    """One opening, trimmed to just what an opening picker filters and displays on. Deliberately
    thinner than `Opening` - the from-schedule request composer selects doors and never needs the
    dimensional/keying detail, so this avoids materializing it."""

    opening_number: str
    building: str | None
    floor: str | None
    location: str | None
    hand: str | None
    door_type: str | None
    frame_type: str | None
    interior_exterior: str | None
    keying: str | None
    leaf_count: int | None


@strawberry.type
class ProjectOpenings:
    """A project's openings for an opening picker, plus the two counts a source card shows. Answers
    a three-field selection without loading every HardwareItem the way `projectHardwareSchedule`
    does - `hardwareItemCount` is a grouped COUNT, not a materialized list."""

    openings: list[ProjectOpeningRow]
    opening_count: int
    hardware_item_count: int


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
class PullRequestItem:
    id: strawberry.ID
    pull_request_id: strawberry.ID
    # Null on a line whose request was raised straight off inventory (#451) - shelf stock carries no
    # opening. Schedule-driven lines keep theirs.
    opening_number: str | None
    hardware_category: str
    product_code: str
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
    # Who cancelled the pull and why (#343). Null unless status is CANCELLED.
    cancelled_by: str | None = None
    cancellation_reason: str | None = None
    # When the pick was confirmed and by whom (#367). This is the moment stock left inventory;
    # `approvedAt` only says the warehouse started on the pull. Staging and completion gate on this.
    picked_at: datetime | None = None
    picked_by: str | None = None
    # Stock has come off the shelf for this pull but it is not fully picked - a short confirm waiting
    # on a second one. Only computed for un-picked pulls (it is meaningless once `pickedAt` is set);
    # null means "not evaluated", never "nothing picked".
    partially_picked: bool | None = None


@strawberry.type
class ShopAssemblyRequestItem:
    """One flat line on a shop-assembly request, tagged with the opening it is owed to."""

    id: strawberry.ID
    shop_assembly_request_id: strawberry.ID
    # Null on a line raised straight off inventory - shelf stock carries no opening.
    opening_number: str | None
    hardware_category: str
    product_code: str
    # What the schedule owed, and what the composer could actually claim. Short is the difference,
    # derived and never stored.
    quantity: int
    allocated_quantity: int


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
    # The warehouse pull this request minted at accept. Null while it is still PENDING.
    pull_request_id: strawberry.ID | None
    items: list[ShopAssemblyRequestItem]
    # Where the request sits on the ladder the requests list draws as columns. Derived from the
    # request's status and its pull's, never stored.
    stage: RequestStage
    # A PENDING request whose minted pull was cancelled was returned by that cancellation (#343):
    # the hardware went back and the request came back for re-acceptance. Human-readable explanation
    # of that reappearance in the queue, else null. Derived, never stored.
    return_note: str | None


@strawberry.type
class ShippingOutRequestItem:
    id: strawberry.ID
    shipping_out_request_id: strawberry.ID
    # Null on a line raised straight off inventory (#451) - shelf stock carries no opening.
    opening_number: str | None
    hardware_category: str
    product_code: str
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
    # Where the request sits on the ladder the requests list draws as columns (mirrors
    # ShopAssemblyRequest.stage). Derived from the request's status and its pull's, never stored.
    stage: RequestStage
    # See ShopAssemblyRequest.return_note (#343).
    return_note: str | None


@strawberry.type
class PackingSlipItem:
    id: strawberry.ID
    packing_slip_id: strawberry.ID
    opening_number: str | None
    # Where the hardware was going, as the slip recorded it at confirm time (#452). The Delivery
    # Request prints these after the opening number, so a reprint says what the driver's copy said.
    building: str | None
    floor: str | None
    location: str | None
    product_code: str
    hardware_category: str
    quantity: int


@strawberry.type
class PackingSlip:
    """A shipment and the Delivery Request that travels with it (#447).

    The header below is the paper form the site signs, so every field of it survives out of
    `packingSlips` unchanged and the document can be reprinted years later exactly as issued. Blanks
    come back as null, which is what the form said too.
    """

    id: strawberry.ID
    packing_slip_number: str
    project_id: strawberry.ID
    # Where the truck has got to. The header is editable only while SCHEDULED.
    status: ShipmentStatus
    shipped_by: str
    shipped_at: datetime
    created_at: datetime
    pickup_date: date | None
    delivery_date: date | None
    shipper_email: str | None
    shipper_phone: str | None
    pickup_location: str | None
    # How the load travelled (#451). A snapshot of the method's name, so a renamed or retired method
    # cannot rewrite what an already-shipped slip says.
    shipment_method: str | None
    carrier_tag_bol: str | None
    weight_lbs: float | None
    delivery_address: str | None
    special_instructions: str | None
    gate_number: str | None
    forklift_onsite: str | None
    material_coming_back: str | None
    site_material_included: str | None
    construction_temp_keys: str | None
    extra_frame_anchors: str | None
    contractor_contact_name: str | None
    contractor_contact_phone: str | None
    ucsh_contact_name: str | None
    ucsh_contact_phone: str | None
    sales_order_number: str | None
    picked_up_at: datetime | None
    picked_up_by: str | None
    delivered_at: datetime | None
    delivered_by: str | None
    items: list[PackingSlipItem]
    # How the load was physically arranged (#451). Empty for a slip cut before containers existed, so
    # the Delivery Request falls back to a flat material list rather than printing nothing. `items` is
    # still the record of what shipped; this is what the person unloading the truck reads.
    containers: list["ShipmentContainer"]


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
    # #293: Start a Request now mints request entities (PENDING), not PullRequests. A signed-in user
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
class ShipReadyLooseItem:
    # Null on stock pulled by a request raised straight off inventory (#451) - it is owed to the
    # project, not to a door.
    opening_number: str | None
    hardware_category: str
    product_code: str
    available_quantity: int


@strawberry.type
class ShipmentContainerItem:
    """One thing placed in a container, and where in the stack it sits (#451)."""

    id: strawberry.ID
    shipment_container_id: strawberry.ID
    opening_number: str | None
    hardware_category: str
    product_code: str
    quantity: int
    # Stacking order. Only meaningful on a skid or a door cart - the two loaded in a sequence
    # somebody reverses at the far end. Position 0 is loaded FIRST, so on a skid it is the bottom.
    position: int


@strawberry.type
class ShipmentContainer:
    """A skid, door cart, box, envelope or bundle the warehouse loads (#451).

    `packingSlipId` is the whole lifecycle: null while it is being built and can be changed, stamped
    once its shipment is confirmed and from then on history.
    """

    id: strawberry.ID
    project_id: strawberry.ID
    container_type: ShipmentContainerType
    name: str
    packing_slip_id: strawberry.ID | None
    created_by: str
    created_at: datetime
    updated_at: datetime
    items: list[ShipmentContainerItem]


@strawberry.type
class StagedLooseItem:
    """One loose product staged for shipping, and how much of it is already in a container (#451)."""

    opening_number: str | None
    hardware_category: str
    product_code: str
    staged_quantity: int
    placed_quantity: int
    # staged - placed: what is still loose on the floor waiting to be put somewhere.
    unplaced_quantity: int


@strawberry.type
class StagingPool:
    """Everything a project has staged for shipping, and where it has been put (#451).

    The left-hand side of the staging workspace reads `unplaced*`; the container cards read
    `containers`. One query rather than two so the two halves can never disagree about whether
    something has been loaded.
    """

    loose_items: list[StagedLooseItem]
    containers: list[ShipmentContainer]


@strawberry.type
class ShipmentMethod:
    """How a load can travel, as the shipping department maintains it (#451).

    Retiring one flips `isActive` rather than deleting it: the Delivery Request form offers only
    active methods, while shipments that already went out under it keep printing their own snapshot
    of the name.
    """

    id: strawberry.ID
    name: str
    is_active: bool
    sort_order: int
    created_at: datetime
    updated_at: datetime


@strawberry.type
class RequestCoverageLine:
    """One product an opening is owed, and where those units have got to.

    The answer both composers read: shop assembly and shipping out ask the same question at
    composition time, so `suggested = max(owed - sent - claimed, 0)` is computed once, in
    `app.repositories.request_composer`, and served here to both.

    Availability is deliberately absent: `projectInventoryAvailability` is the single answer to
    "what may I claim" (#342) and the creation gate is applied against that number, so a composer
    joins the two by (hardwareCategory, productCode) rather than reading a second figure from here
    that could disagree with the one it is held to.
    """

    opening_number: str
    hardware_category: str
    product_code: str
    # SITE_HARDWARE goes to site loose; SHOP_HARDWARE is fitted at the bench. Null means the
    # schedule was never classified, which the composer shows as its own group rather than guessing
    # on the user's behalf.
    classification: Classification | None
    # What the CURRENT schedule says this opening takes, summed across its leaves.
    owed_quantity: int
    # What has left the building for this opening: completed shop-assembly pulls, plus shipping-out
    # (the completed pull and the slip cut from it folded together, never added).
    sent_quantity: int
    # What somebody else is already holding: lines on pending requests and on live pulls.
    claimed_quantity: int
    # `max(owed - sent - claimed, 0)`. Zero rather than negative when a re-upload lowers the
    # schedule below what has already gone out - nothing is ever auto-unwound.
    suggested_quantity: int
    # Placed with a vendor and not yet received, project-wide for this product. Not an allocation to
    # this opening - it answers "is more coming, or is this all there will ever be".
    on_order_quantity: int


@strawberry.type
class ShipReadyItems:
    loose_items: list[ShipReadyLooseItem]


@strawberry.type
class InventoryItemDetail:
    inventory_location: InventoryLocation
    po_number: str | None
    classification: Classification | None
    unit_cost: float | None


@strawberry.type
class ReceiveRow:
    """One receive entity for the warehouse Receives page (#505).

    Deliberately a flat, discriminated row rather than a union: drafts and booked records are the
    same thing at different stages, and the page reads them in one interleaved list. `kind` says
    which it is; `receipt_number` is only ever set on a booked record, `rejection_reason` only on a
    rejected draft."""

    kind: str
    id: strawberry.ID
    occurred_at: datetime
    status: str
    po_id: strawberry.ID
    po_number: str | None
    project_id: strawberry.ID | None
    project_name: str | None
    warehouse_id: strawberry.ID | None
    line_count: int
    total_quantity: int
    counted_by: str | None
    reviewed_by: str | None
    rejection_reason: str | None
    receipt_number: str | None
    batch_number: str | None


@strawberry.type
class InventoryRow:
    """One stocked inventory line, flat (#506).

    The Hardware Items view is a table now rather than a category -> product -> location accordion,
    so every value the warehouse sorts, filters or exports on sits on the row itself instead of
    being spread across three levels of node."""

    inventory_location: InventoryLocation
    unit_cost: float
    line_value: float
    po_number: str | None
    vendor_name: str | None
    warehouse_code: str
    warehouse_name: str
    project_number: str
    project_name: str
    # False when this row's (category, code) appears nowhere in the project's imported hardware
    # schedule, so no pull request can ever claim it: both request builders start from the schedule,
    # and they match on the exact pair. Stock that entered outside an import - the SharePoint
    # migration, a stock allocation, a reclassify - can carry a spelling the schedule does not use,
    # and until someone reconciles the two the units are invisible to the people who need them.
    # Defaults True so the unscoped view, which spans projects and has no single schedule to compare
    # against, does not assert an absence it never checked.
    matches_schedule: bool = True


@strawberry.type
class EmailPoResult:
    """The outcome of sending a PO to its vendor (#500).

    A result rather than an exception, because every refusal is something the user can act on -
    generate the document, register the PO, ask accounting to put an email on the vendor card - and
    none of them means something broke."""

    sent: bool
    message: str
    sent_to: str | None = None


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

    `available = on_hand - deficient - reserved`, floored at 0 - the exact number the Start-a-Request
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
    # The dominant SITE/SHOP classification of this product on the schedule, project-wide (#610), or
    # null when the schedule never named it or never classified it. Lets a loose extras line carry the
    # same chip and shop framing as the opening-tagged catalog rows above it.
    classification: Classification | None


@strawberry.type
class PickSheetOpening:
    """One opening a pick section's units are owed to (#367).

    Every opening is listed, never summarised into "and N more": the picker is building carts per
    door, so the list of openings *is* the work, and a truncated one sends them back to another
    screen."""

    # Null on an unattributed line (#451): the units are owed to the project, not to a door, so
    # there is no cart to name and the picker just puts them on the shipment.
    opening_number: str | None
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
    # #496: the vendor's name for the part and the PO it arrived on, per location - one product can
    # sit in inventory from several POs with different Order As values. Null on stock-origin rows.
    order_as: str | None
    po_number: str | None


@strawberry.type
class PickSheetSection:
    """One product code to pick, with every opening it is owed to and everywhere it can come from."""

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
    openings: list[PickSheetOpening]
    locations: list[PickSheetLocation]


@strawberry.type
class PickSheet:
    """Everything the pick screen and the printed sheet render from (#367)."""

    pull_request: PullRequest
    sections: list[PickSheetSection]


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
    stock_items: list["StockItem"]


@strawberry.type
class LocationVariant:
    aisle: str | None
    row: str | None
    bay: str | None


@strawberry.type
class LocationDuplicateGroup:
    # A collision is only meaningful within one warehouse - the same triple in two warehouses is two
    # groups, so a group names its warehouse and the merge it offers acts on that warehouse alone.
    warehouse_id: strawberry.ID | None
    warehouse_label: str | None
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
    # Stock pool: units on hand, their off-PO value (migrated stock carries its own unit cost;
    # PO-received pool stock counts 0), and rows with no aisle.
    stock_item_count: int
    stock_value: float
    stock_unlocated_count: int
    pending_pull_shop: int
    pending_pull_shipping: int
    received_last_7_days: int
    back_ordered_count: int
    deficient_count: int
    # Counted receives waiting on a Warehouse Manager.
    pending_receive_draft_count: int


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
class HardwareStatusByProduct:
    """One product's lifecycle counts, summed across the projects the admin selected.

    `sent_to_shop` is an exit, not a stage: shop assembly is outside the Nexus pipeline, so a
    completed shop pull leaves the system the same way a packing slip does.
    """

    hardware_category: str
    product_code: str
    required_quantity: int
    not_purchased: int
    po_drafted: int
    on_order: int
    received_quantity: int
    on_hand: int
    sent_to_shop: int
    staged_for_shipping: int
    # Gross packing-slip exits; returns never decrement it.
    shipped_out: int
    # RETURN_TO_PROJECT shipment-return units: back in on_hand while still inside the gross
    # shipped_out, so a reader summing "where the units are" must subtract this once.
    returned_to_project: int


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
    # Off-PO cost per unit (the SharePoint migration writes it; a PO-received pool row carries none).
    unit_cost: float | None
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
class ShippingStats:
    """The Shipping landing's pipeline gauges (#589), read left to right as the work flows: a request
    waits to be accepted, its pull is staged into containers, the shipment is booked, then it is on
    the road. Delivered is the resting state and carries no gauge."""

    # PENDING ShippingOutRequests waiting on someone to accept them.
    pending_request_count: int
    # Open ShipmentContainers (no packing slip yet) - the loads still being built on the floor.
    staging_container_count: int
    # Confirmed shipments still SCHEDULED: booked, editable, waiting for the carrier.
    scheduled_shipment_count: int
    # Shipments PICKED_UP but not yet delivered - in transit.
    in_transit_shipment_count: int


@strawberry.type
class AdminStats:
    user_count: int
    hardware_item_count: int
    opening_count: int
    # Whether the Database Access page is live in this environment (db-admin-postgres-access). AdminLanding
    # already fetches adminStats, so carrying the flag here lets the DB-access card and route hide with no
    # extra query - off in local dev, CI and every PR preview, on only where the proxy is configured.
    db_access_enabled: bool


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
class ApproveReceiveDraftResult:
    """What approving a draft did.

    Same wrapper `CreateReceiveResult` was (#353 PR E), because approval is where that pipeline moved
    to: `queued` true means the relay was unreachable and the receipt is on the durable outbox, so
    `receiveRecord` is null and nothing is in inventory yet. The draft is APPROVED either way - what
    it must never be is approvable twice."""

    queued: bool
    draft: ReceiveDraft
    receive_record: ReceiveRecord | None = None
    outbox_entry_id: strawberry.ID | None = None


@strawberry.type
class SharepointInventoryItem:
    """One row of the legacy SharePoint inventory list, as read.

    Deliberately un-interpreted: quantities are the source columns, not a Nexus destination, and
    `locations` is the raw free-text string ("A-62R", "F-37, F-58", "Warehouse Overflow"). The
    wizard parses and maps; keeping the raw values here is what lets the first step report source
    totals that reconcile against SharePoint itself.
    """

    sp_item_id: str
    part_number: str
    scheduled_part_number: str
    part_category: str
    inventory_type: str
    locations: str
    stock_qty: int
    non_stock_qty: int
    project_inventory_qty: int
    project_number: str
    project_name: str
    # Cost per unit off the source list. There is no PO line in Nexus for migrated stock, so this is
    # the only cost the units can carry; the migration writes it onto the inventory rows.
    unit_cost: float
    # What describes a non-schedule product, since no hardware schedule does (#454).
    part_description: str
    finish: str
    rating: str
    mounting: str
    height_inches: str
    width_inches: str


@strawberry.type
class SharepointInventorySnapshot:
    items: list[SharepointInventoryItem]
    # True when the migration has already run (a run marker exists). Definitive, unlike the old
    # has-any-inventory check: running it twice doubles every row it wrote, so the wizard warns first.
    already_migrated: bool


@strawberry.type
class ProjectScheduleProduct:
    """One schedule (category, code) PAIR of a project, for the migration wizard's snap + classification.

    One row per pair, NOT one per code: a code split across categories is several pairs, and the
    wizard splits the migrated quantity across them by `required_quantity` so the minority pair's
    rows still get marked and classified. `classification` is the pair's dominant Site/Shop value,
    or null where the schedule never classified it (the step asks for a pick there)."""

    project_id: strawberry.ID
    hardware_category: str
    product_code: str
    classification: Classification | None
    required_quantity: int


@strawberry.type
class MigrationResult:
    stock_items: int
    project_locations: int
    total_units: int
    # Non-schedule products catalogued (#454). `skipped` is codes already in the catalog, which is
    # a normal outcome rather than a failure.
    catalog_items_created: int = 0
    catalog_items_skipped: int = 0
    catalog_attributes_created: int = 0
