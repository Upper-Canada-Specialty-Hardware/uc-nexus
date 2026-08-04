import enum


class Classification(str, enum.Enum):
    SITE_HARDWARE = "SITE_HARDWARE"
    SHOP_HARDWARE = "SHOP_HARDWARE"


class HardwareItemState(str, enum.Enum):
    AVAILABLE = "AVAILABLE"
    IN_PO = "IN_PO"


class POStatus(str, enum.Enum):
    # GP_REGISTERED means "the PO exists in GP". A PO that fails to create in GP is never created in
    # UC Nexus either, so there is no FAILED state and no separate gp_sync_status; the status carries it.
    DRAFT = "DRAFT"
    GP_REGISTERED = "GP_REGISTERED"
    VENDOR_CONFIRMED = "VENDOR_CONFIRMED"
    PARTIALLY_RECEIVED = "PARTIALLY_RECEIVED"
    CLOSED = "CLOSED"
    CANCELLED = "CANCELLED"


class PullRequestSource(str, enum.Enum):
    SHOP_ASSEMBLY = "SHOP_ASSEMBLY"
    SHIPPING_OUT = "SHIPPING_OUT"


class PullRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class PullRequestItemType(str, enum.Enum):
    LOOSE = "LOOSE"
    OPENING_ITEM = "OPENING_ITEM"


class PullPickLineState(str, enum.Enum):
    """Whether a dictated pick line has moved inventory yet (#367).

    DRAFT is the sheet still being keyed in - saved so it survives a reload, deducting nothing, and
    replaced wholesale by the next save. APPLIED is a confirmed pick: the units are off the shelf
    and the row is history.
    """

    DRAFT = "DRAFT"
    APPLIED = "APPLIED"


class ShipmentContainerType(str, enum.Enum):
    """What the warehouse physically loads a shipment into (#451).

    SKID and DOOR_CART are the two that carry an ordered stack somebody has to unload in reverse, so
    they are the ones whose `position` means anything. The other three hold things whose order does
    not matter.
    """

    SKID = "SKID"
    DOOR_CART = "DOOR_CART"
    BOX = "BOX"
    ENVELOPE = "ENVELOPE"
    BUNDLE = "BUNDLE"


class OpeningItemState(str, enum.Enum):
    IN_INVENTORY = "IN_INVENTORY"
    SHIP_READY = "SHIP_READY"
    SHIPPED_OUT = "SHIPPED_OUT"


class ReceiveDraftStatus(str, enum.Enum):
    """Where a counted-but-not-yet-posted receive is in the approval loop.

    A receive used to be one action: the relay posted the GP receipt and Nexus credited inventory in
    the same call. It is now two, split at the point where the count stops being one person's word.
    The draft is Nexus-only - nothing reaches GP and nothing lands on a shelf - until a Warehouse
    Manager has looked at it.

    APPROVING is a claim, not a resting state. The GP write is a relay round trip, and a database
    lock cannot be held across it (see the create_receipt call in schemas/warehouse.py), so approve
    stamps this status in its own committed transaction first. That is what makes a second approver
    bounce off instead of posting a duplicate GP receipt. A draft parked here is one whose approval
    died mid-flight; retrying with the same idempotency key resumes it.

    APPROVED with a null receive_record_id is not a contradiction: the relay was offline, the receipt
    is on the durable outbox, and the ReceiveRecord appears when it drains. The draft is finished
    either way - what it must never be is approvable a second time.
    """

    PENDING_APPROVAL = "PENDING_APPROVAL"
    APPROVING = "APPROVING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ReceiveDecisionStatus(str, enum.Enum):
    PENDING = "PENDING"
    DECIDED = "DECIDED"


class ReceiveDecisionChoice(str, enum.Enum):
    """What the person who raised the PO wants done with a shipment that just landed.

    Recording the choice is all this does. SHIP_OUT does not create a shipping-out request: only the
    hardware schedule knows which opening and leaf a fungible quantity is owed to, so re-attaching
    that identity stays where it lives - Start a Task, which the frontend deep-links into once the
    choice is recorded. See docs/HARDWARE_IDENTITY_LIFECYCLE.md.
    """

    KEEP_IN_INVENTORY = "KEEP_IN_INVENTORY"
    SHIP_OUT = "SHIP_OUT"


class ShopAssemblyRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ShippingOutRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ShipmentStatus(str, enum.Enum):
    """Where a confirmed shipment is on its physical journey (#447).

    A packing slip used to be a single moment - it was cut and that was the end of it. It is now a
    Delivery Request that outlives its own creation: the paper is written days before a truck comes,
    the driver takes it, and the site signs for it. These three states are that journey and nothing
    more. **No inventory moves between them.** `confirm_shipment` is still what claims the hardware
    (opening items go SHIPPED_OUT, loose lines come off what is available to ship), because that is
    the moment the warehouse committed it; PICKED_UP and DELIVERED only record where it got to.

    SCHEDULED is also the one editable state. Once the Delivery Request has been picked up, a driver
    is carrying a printed copy of it, and the stored record has to keep matching what they hold.
    """

    SCHEDULED = "SCHEDULED"
    PICKED_UP = "PICKED_UP"
    DELIVERED = "DELIVERED"


class ReservationSource(str, enum.Enum):
    """Which kind of request an InventoryReservation is held for (#342). The discriminator is
    explicit rather than inferred from whichever FK is populated, so a query can filter on it
    without an OR over nullable columns."""

    SHOP_ASSEMBLY_REQUEST = "SHOP_ASSEMBLY_REQUEST"
    SHIPPING_OUT_REQUEST = "SHIPPING_OUT_REQUEST"
    # A PR-REPL replacement pull, which holds its claim directly rather than through a request
    # (there is no request behind a deficiency). Minted the moment a unit is flagged deficient at the
    # bench, so the replacement is not left competing for stock at approval time against requests
    # that were created after the defect was found.
    REPLACEMENT_PULL = "REPLACEMENT_PULL"


class PullStatus(str, enum.Enum):
    """How much of something has been staged by the warehouse.

    Persisted per `ShopAssemblyOpening`, where only NOT_PULLED and PULLED are ever written: one
    opening is a cart, and a cart is either built or it is not. PARTIAL is the *aggregate* reading
    over a set of openings - "some of this pull is staged, some is not" - and since #343 it is
    derived for a whole PullRequest rather than stored (see
    `warehouse.get_pull_staging_summaries`). Keeping it out of the opening column is what stops a
    half-truth being persisted about a single cart."""

    NOT_PULLED = "NOT_PULLED"
    PARTIAL = "PARTIAL"
    PULLED = "PULLED"


class AssemblyStatus(str, enum.Enum):
    PENDING = "PENDING"
    # Some hardware has been recorded against the leaf but it is not fully dispositioned yet (#340).
    # An IN_PROGRESS opening is still the assembler's work: it stays in My Work and can be handed to
    # someone else by a manager, because every unit counted so far is persisted on the item rows.
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"


class PODocumentType(str, enum.Enum):
    PO_DOCUMENT = "PO_DOCUMENT"
    VENDOR_ACKNOWLEDGEMENT = "VENDOR_ACKNOWLEDGEMENT"
    MISCELLANEOUS = "MISCELLANEOUS"
    # The finished supplier PO document generated by Nexus (issue #230), saved back onto the PO.
    GENERATED_PO = "GENERATED_PO"


class NotificationType(str, enum.Enum):
    PULL_REQUEST_CANCELLED = "PULL_REQUEST_CANCELLED"
    PULL_REQUEST_COMPLETED = "PULL_REQUEST_COMPLETED"
    SHIPMENT_COMPLETED = "SHIPMENT_COMPLETED"
    # PO "couldn't be fulfilled - backfill needed" signal from the inventory-sufficiency gates (#224).
    # Carries the per-combo shortfall detail in its message.
    INVENTORY_SHORTFALL = "INVENTORY_SHORTFALL"
    # A PR-REPL replacement pull completed for a leaf that had already shipped (#341). The hardware
    # is real and is owed to an opening that is no longer in the building, so it must not be left to
    # sit silently in the shop - this is the signal that routes it into reallocation/site shipment.
    REPLACEMENT_AFTER_SHIPMENT = "REPLACEMENT_AFTER_SHIPMENT"
    # Openings became workable on the assembly floor (#344): the warehouse staged one or more carts,
    # or completed a pull that still had un-staged openings on it. Addressed to the shop-assembly
    # manager audience, because the actionable consequence is that the assignment board has work in
    # it that nobody is holding yet. Raised once per staging confirmation, never per opening.
    ASSEMBLY_WORK_AVAILABLE = "ASSEMBLY_WORK_AVAILABLE"
    # Replacement hardware arrived for a leaf that has NOT shipped (#344), addressed to the
    # assembler holding it. The shipped case has its own type above, because it is somebody else's
    # problem entirely; this one is "go and fit it", and it is the missing half of the #341 loop.
    REPLACEMENT_ARRIVED = "REPLACEMENT_ARRIVED"
    # A PENDING replacement (PR-REPL) pull that could not be covered is now coverable, because a
    # receive landed the stock it was waiting on (#344). Addressed to the warehouse: a replacement
    # pull holds no reservation (a deficiency cannot be foreseen), so nothing else was going to tell
    # anybody it had become approvable. Deduped to one *unread* notification per pull.
    PULL_UNBLOCKED = "PULL_UNBLOCKED"
    # A queued GP write died for good (#353 PR E): GP rejected it, it is ambiguous (GP may hold it),
    # the UC Nexus persist refused it after GP had already committed, or it exhausted its retries.
    # The outbox absorbs an offline relay silently and by design, so this is the one outcome a human
    # has to be told about - without it, "queued" and "quietly dead" look identical from the floor.
    GP_WRITE_FAILED = "GP_WRITE_FAILED"
    # A counted receive is waiting on a Warehouse Manager. Addressed to the manager audience, not the
    # floor: everyone who can approve needs to know there is a queue, and the person who submitted it
    # already knows.
    RECEIVE_DRAFT_SUBMITTED = "RECEIVE_DRAFT_SUBMITTED"
    # A manager sent a draft back. Person-targeted (the author's Clerk user id in recipient_role),
    # because a rejection is owed to exactly the person who has to act on it.
    RECEIVE_DRAFT_REJECTED = "RECEIVE_DRAFT_REJECTED"
    # Hardware somebody ordered has landed and they have to say where it goes - project inventory or
    # straight back out to site. Person-targeted at the PO's creator: this is a purchasing decision
    # about their own order, and broadcasting it would make it nobody's.
    RECEIVE_DECISION_REQUIRED = "RECEIVE_DECISION_REQUIRED"


class AuditEntityType(str, enum.Enum):
    INVENTORY_LOCATION = "INVENTORY_LOCATION"
    OPENING_ITEM = "OPENING_ITEM"
    STOCK_ITEM = "STOCK_ITEM"
    # The assembly work unit (one door leaf) an INSTALL_PROGRESS event is recorded against (#340).
    # Progress happens before any OpeningItem exists, so it cannot hang off OPENING_ITEM.
    SHOP_ASSEMBLY_OPENING = "SHOP_ASSEMBLY_OPENING"
    # The pull itself (#343). A cancellation is an event about the *pull*, not about any one
    # inventory row it happened to touch, so it needs an entity of its own rather than being
    # smuggled onto an INVENTORY_LOCATION row.
    PULL_REQUEST = "PULL_REQUEST"


class AuditAction(str, enum.Enum):
    ADJUSTMENT = "ADJUSTMENT"
    MOVE = "MOVE"
    UNLOCATE = "UNLOCATE"
    RECEIVE = "RECEIVE"
    PULL_DEDUCTION = "PULL_DEDUCTION"
    SPOT_CHECK = "SPOT_CHECK"
    PUT_AWAY = "PUT_AWAY"
    DESTOCK = "DESTOCK"
    ALLOCATE_FROM_STOCK = "ALLOCATE_FROM_STOCK"
    RECLASSIFY = "RECLASSIFY"
    REPORT_DEFICIENT = "REPORT_DEFICIENT"
    RESOLVE_DEFICIENT = "RESOLVE_DEFICIENT"
    TRANSFER = "TRANSFER"
    RETURN = "RETURN"
    # An assembler recorded how many units of a checklist line are installed on a leaf (#340).
    INSTALL_PROGRESS = "INSTALL_PROGRESS"
    # The leaf was called finished and materialized as an OpeningItem (#340). Progress saves are no
    # longer the same call as completion, so the two moments need distinct audit records.
    ASSEMBLY_COMPLETE = "ASSEMBLY_COMPLETE"
    # A PR-REPL replacement pull completed and gave the leaf its expectation back (#341): the units
    # left deficient_quantity, either as remaining work (leaf still open) or as
    # replacement_pending_quantity (leaf already completed).
    REPLACEMENT_RECEIVED = "REPLACEMENT_RECEIVED"
    # Replacement hardware was fitted to an already-completed leaf (#341) - the one legitimate write
    # to an OpeningItem's installed hardware after assembly finished.
    REPLACEMENT_INSTALL = "REPLACEMENT_INSTALL"
    # One opening of a shop-assembly pull was confirmed staged - its cart is built (#343). Recorded
    # against the SHOP_ASSEMBLY_OPENING, because staging is per opening and the pull as a whole may
    # still be part-way through.
    PULL_STAGED = "PULL_STAGED"
    # The inverse of PULL_DEDUCTION (#343): a cancelled pull put its hardware back on the shelf.
    # Distinct from RETURN (a shipment coming back from site) so a restock is never mistaken for
    # inventory arriving from outside the building.
    PULL_RESTOCK = "PULL_RESTOCK"
    # A pull was cancelled after approval (#343). One row per cancellation against the PULL_REQUEST,
    # carrying what was restocked, which openings were released, and what happened to the source
    # request - the PULL_RESTOCK rows above are the per-inventory-row detail of the same event.
    PULL_CANCELLED = "PULL_CANCELLED"


class ReturnDisposition(str, enum.Enum):
    """Where a returned loose-hardware line goes when a shipment comes back."""

    RETURN_TO_PROJECT = "RETURN_TO_PROJECT"
    NON_STOCK = "NON_STOCK"
    RMA_DEFECTIVE = "RMA_DEFECTIVE"


class DestockSource(str, enum.Enum):
    CANCELLATION = "CANCELLATION"
    DEFICIENT_SWAP = "DEFICIENT_SWAP"
    OVERAGE = "OVERAGE"
    OTHER = "OTHER"


class DeficiencyResolution(str, enum.Enum):
    SEND_TO_STOCK = "SEND_TO_STOCK"
    SCRAP = "SCRAP"
    REPAIR = "REPAIR"
    RETURN_TO_VENDOR = "RETURN_TO_VENDOR"
    LEAVE_AS_DEFICIENT = "LEAVE_AS_DEFICIENT"


class DeficientItemSource(str, enum.Enum):
    PROJECT_INVENTORY = "PROJECT_INVENTORY"
    STOCK_POOL = "STOCK_POOL"
