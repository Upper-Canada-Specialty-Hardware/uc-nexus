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
    PullPickLineState as PullPickLineStateDB,
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
    ReceiveDecisionChoice as ReceiveDecisionChoiceDB,
)
from app.models.enums import (
    ReceiveDecisionStatus as ReceiveDecisionStatusDB,
)
from app.models.enums import (
    ReceiveDraftStatus as ReceiveDraftStatusDB,
)
from app.models.enums import (
    ReturnDisposition as ReturnDispositionDB,
)
from app.models.enums import (
    ShipmentStatus as ShipmentStatusDB,
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
PullPickLineState = strawberry.enum(PullPickLineStateDB)
OpeningItemState = strawberry.enum(OpeningItemStateDB)
ShopAssemblyRequestStatus = strawberry.enum(ShopAssemblyRequestStatusDB)
ShippingOutRequestStatus = strawberry.enum(ShippingOutRequestStatusDB)
ShipmentStatus = strawberry.enum(ShipmentStatusDB)
PullStatus = strawberry.enum(PullStatusDB)
AssemblyStatus = strawberry.enum(AssemblyStatusDB)
NotificationType = strawberry.enum(NotificationTypeDB)
PODocumentType = strawberry.enum(PODocumentTypeDB)
DestockSource = strawberry.enum(DestockSourceDB)
DeficiencyResolution = strawberry.enum(DeficiencyResolutionDB)
DeficientItemSource = strawberry.enum(DeficientItemSourceDB)
ReturnDisposition = strawberry.enum(ReturnDispositionDB)
ReceiveDraftStatus = strawberry.enum(ReceiveDraftStatusDB)
ReceiveDecisionStatus = strawberry.enum(ReceiveDecisionStatusDB)
ReceiveDecisionChoice = strawberry.enum(ReceiveDecisionChoiceDB)


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
class PickOutcome(enum.Enum):
    """What `confirmPick` did (#367). Two values, because `confirm_pick` returns exactly two.

    It replaces `ApproveOutcome`, whose two values described a moment that no longer exists:
    approval stopped being the thing that touches inventory. The mapping is not one-to-one, which is
    why the enum is not simply renamed - INSUFFICIENT meant "nothing happened, the pull is blocked
    and still PENDING", while SHORT means "some of it happened, the pull is In Progress and holds
    real deducted stock". Neither is GraphQL-only trivia the client can guess at, so the rename is
    the honest signal that the state machine changed.
    """

    # Every combo is covered. The pull is stamped picked and can be staged.
    PICKED = "picked"
    # Some units were picked and some were not. The pull stays In Progress and un-picked, purchasing
    # is notified for backfill, and a later confirmation enters the remainder.
    SHORT = "short"


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


@strawberry.enum
class GpOutboxStatus(enum.Enum):
    """Where a queued GP write has got to (#353 PR E). Stored as a String + CHECK rather than a PG
    enum (precedent: migration 065), so this list can grow without an ALTER TYPE."""

    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
