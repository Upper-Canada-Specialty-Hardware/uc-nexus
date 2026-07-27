import enum

import strawberry

from app.models.enums import (
    AssemblyStatus as AssemblyStatusDB,
)
from app.models.enums import (
    AuditAction as AuditActionDB,
)
from app.models.enums import (
    AuditEntityType as AuditEntityTypeDB,
)
from app.models.enums import (
    Classification as ClassificationDB,
)
from app.models.enums import (
    DeficiencyResolution as DeficiencyResolutionDB,
)
from app.models.enums import (
    DeficientItemSource as DeficientItemSourceDB,
)
from app.models.enums import (
    DestockSource as DestockSourceDB,
)
from app.models.enums import (
    HardwareItemState as HardwareItemStateDB,
)
from app.models.enums import (
    NotificationType as NotificationTypeDB,
)
from app.models.enums import (
    OpeningItemState as OpeningItemStateDB,
)
from app.models.enums import (
    PODocumentType as PODocumentTypeDB,
)
from app.models.enums import (
    POStatus as POStatusDB,
)
from app.models.enums import (
    PullRequestItemType as PullRequestItemTypeDB,
)
from app.models.enums import (
    PullRequestSource as PullRequestSourceDB,
)
from app.models.enums import (
    PullRequestStatus as PullRequestStatusDB,
)
from app.models.enums import (
    PullStatus as PullStatusDB,
)
from app.models.enums import (
    ReturnDisposition as ReturnDispositionDB,
)
from app.models.enums import (
    ShippingOutRequestStatus as ShippingOutRequestStatusDB,
)
from app.models.enums import (
    ShopAssemblyRequestStatus as ShopAssemblyRequestStatusDB,
)

# Wrap DB enums for Strawberry GraphQL
AuditAction = strawberry.enum(AuditActionDB)
AuditEntityType = strawberry.enum(AuditEntityTypeDB)
Classification = strawberry.enum(ClassificationDB)
HardwareItemState = strawberry.enum(HardwareItemStateDB)
POStatus = strawberry.enum(POStatusDB)
PullRequestSource = strawberry.enum(PullRequestSourceDB)
PullRequestStatus = strawberry.enum(PullRequestStatusDB)
PullRequestItemType = strawberry.enum(PullRequestItemTypeDB)
OpeningItemState = strawberry.enum(OpeningItemStateDB)
ShopAssemblyRequestStatus = strawberry.enum(ShopAssemblyRequestStatusDB)
ShippingOutRequestStatus = strawberry.enum(ShippingOutRequestStatusDB)
PullStatus = strawberry.enum(PullStatusDB)
AssemblyStatus = strawberry.enum(AssemblyStatusDB)
NotificationType = strawberry.enum(NotificationTypeDB)
PODocumentType = strawberry.enum(PODocumentTypeDB)
DestockSource = strawberry.enum(DestockSourceDB)
DeficiencyResolution = strawberry.enum(DeficiencyResolutionDB)
DeficientItemSource = strawberry.enum(DeficientItemSourceDB)
ReturnDisposition = strawberry.enum(ReturnDispositionDB)


# GraphQL-only enums (not stored in database)
@strawberry.enum
class ReconciliationStatus(enum.Enum):
    PO_DRAFTED = "po_drafted"
    ORDERED = "ordered"
    RECEIVED = "received"
    ASSEMBLING = "assembling"
    ASSEMBLED = "assembled"
    SHIPPING_OUT = "shipping_out"
    SHIPPED_OUT = "shipped_out"
    NOT_COVERED = "not_covered"
    BY_OTHERS = "by_others"


@strawberry.enum
class ApproveOutcome(enum.Enum):
    """What `approvePullRequest` did. Two values, because `approve_pull_request` returns exactly two
    outcome strings.

    A third value, CANCELLED, was removed in #344 as dead state. It dated from the pre-#224
    behaviour where an approve that found insufficient stock *cancelled* the pull; since #224 such
    an approve leaves the PR PENDING (blocked, not cancelled) and returns INSUFFICIENT with the
    shortfall detail, so no code path could produce it and no client branched on it. It is safe to
    delete without a migration: ApproveOutcome is a GraphQL-only enum and was never persisted -
    a *cancelled pull* is `PullRequestStatus.CANCELLED`, which is a different enum on a real column
    and is very much alive since #343."""

    APPROVED = "approved"
    # #224: an approve blocked by insufficient inventory leaves the PR PENDING (not cancelled) and
    # returns the shortfall to the approver; the PO is notified for backfill.
    INSUFFICIENT = "insufficient"


@strawberry.enum
class PipelineStage(enum.Enum):
    """How far one door leaf has travelled through shop assembly (#344), derived from existing
    state - no column stores it.

    The ladder is the one the floor actually asks about: *where is opening A01 leaf 2?* Each value
    is the furthest point the leaf has provably reached, so the stage of a whole request is the
    stage of its least-advanced opening - what is holding it up.

    REJECTED and CANCELLED are off the ladder rather than on the end of it: they are the two ways a
    leaf leaves the pipeline without being assembled, and reading them as "further along than
    IN_PROGRESS" would be nonsense.
    """

    # The request exists and is waiting for a human to accept it. No pull has been minted.
    REQUESTED = "REQUESTED"
    # Accepted: the warehouse pull exists but has not been approved, so nothing has been picked.
    ACCEPTED = "ACCEPTED"
    # The pull is approved and stock is deducted, but this opening's own cart is not built yet.
    PULLING = "PULLING"
    # This opening's cart is staged (#343) and nobody is holding it - it is on the assignment board.
    STAGED = "STAGED"
    # Claimed by an assembler, with nothing recorded against it yet.
    ASSIGNED = "ASSIGNED"
    # Hardware has been recorded onto the leaf but it is not fully dispositioned (#340).
    IN_PROGRESS = "IN_PROGRESS"
    # Assembled: an OpeningItem exists for the leaf and it is in (or ready to leave) inventory.
    COMPLETED = "COMPLETED"
    # The assembled leaf has left the building.
    SHIPPED = "SHIPPED"
    # The source request was rejected, which released its claim on inventory.
    REJECTED = "REJECTED"
    # The pull this opening was on was cancelled and its hardware restocked (#343). The opening is
    # back on a PENDING request awaiting re-acceptance, so this is a state the *history* is in.
    CANCELLED = "CANCELLED"


@strawberry.enum
class TransferSourceType(enum.Enum):
    INVENTORY_LOCATION = "INVENTORY_LOCATION"
    STOCK_ITEM = "STOCK_ITEM"


@strawberry.enum
class LeafStatus(enum.Enum):
    """Per-leaf status in the per-opening leaf-status rollup (#313). The first three mirror
    OpeningItemState; NOT_ASSEMBLED is synthetic - a leaf the schedule expects (1..leaf_count) that
    has no OpeningItem yet."""

    NOT_ASSEMBLED = "NOT_ASSEMBLED"
    IN_INVENTORY = "IN_INVENTORY"
    SHIP_READY = "SHIP_READY"
    SHIPPED_OUT = "SHIPPED_OUT"
