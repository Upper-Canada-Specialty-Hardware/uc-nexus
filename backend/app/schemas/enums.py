import enum

import strawberry

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
    PODocumentType as PODocumentTypeDB,
)
from app.models.enums import (
    POStatus as POStatusDB,
)
from app.models.enums import (
    PullPickLineState as PullPickLineStateDB,
)
from app.models.enums import (
    PullRequestSource as PullRequestSourceDB,
)
from app.models.enums import (
    PullRequestStatus as PullRequestStatusDB,
)
from app.models.enums import (
    ReceiveDraftStatus as ReceiveDraftStatusDB,
)
from app.models.enums import (
    ReturnDisposition as ReturnDispositionDB,
)
from app.models.enums import (
    ShipmentContainerType as ShipmentContainerTypeDB,
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
PullPickLineState = strawberry.enum(PullPickLineStateDB)
ShopAssemblyRequestStatus = strawberry.enum(ShopAssemblyRequestStatusDB)
ShippingOutRequestStatus = strawberry.enum(ShippingOutRequestStatusDB)
ShipmentStatus = strawberry.enum(ShipmentStatusDB)
ShipmentContainerType = strawberry.enum(ShipmentContainerTypeDB)
NotificationType = strawberry.enum(NotificationTypeDB)
PODocumentType = strawberry.enum(PODocumentTypeDB)
DestockSource = strawberry.enum(DestockSourceDB)
DeficiencyResolution = strawberry.enum(DeficiencyResolutionDB)
DeficientItemSource = strawberry.enum(DeficientItemSourceDB)
ReturnDisposition = strawberry.enum(ReturnDispositionDB)
ReceiveDraftStatus = strawberry.enum(ReceiveDraftStatusDB)


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
class RequestStage(enum.Enum):
    """Where one request sits on the ladder the requests list draws as columns.

    Derived from the request's own status and the state of the pull it minted - no column stores it.
    REJECTED is off the ladder rather than on the end of it: it is how a request leaves without ever
    being pulled, and reading it as "further along than PULLING" would be nonsense.
    """

    # The request exists and is waiting for a reviewer to accept it. No pull has been minted.
    REQUESTED = "REQUESTED"
    # Accepted: the warehouse pull exists but nobody has started picking it.
    ACCEPTED = "ACCEPTED"
    # The pull is being picked.
    PULLING = "PULLING"
    # The pull completed. That is the last thing v1 records about this hardware.
    DONE = "DONE"
    # The request was rejected, which released its claim on inventory.
    REJECTED = "REJECTED"


@strawberry.enum
class TransferSourceType(enum.Enum):
    INVENTORY_LOCATION = "INVENTORY_LOCATION"
    STOCK_ITEM = "STOCK_ITEM"


@strawberry.enum
class GpOutboxStatus(enum.Enum):
    """Where a queued GP write has got to (#353 PR E). Stored as a String + CHECK rather than a PG
    enum (precedent: migration 065), so this list can grow without an ALTER TYPE."""

    PENDING = "PENDING"
    IN_FLIGHT = "IN_FLIGHT"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


@strawberry.enum
class MigrationDestination(enum.Enum):
    """Where a migrated SharePoint row lands.

    PROJECT is a project's own inventory (SharePoint's "Project Inventory Qty"); STOCK is the
    company shelf pool ("Stock Qty" + "Non Stock Qty"). GraphQL-only - nothing persists this, it
    just routes one entry down one of two existing write paths.
    """

    PROJECT = "PROJECT"
    STOCK = "STOCK"
