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
    APPROVED = "approved"
    CANCELLED = "cancelled"
    # #224: an approve blocked by insufficient inventory leaves the PR PENDING (not cancelled) and
    # returns the shortfall to the approver; the PO is notified for backfill.
    INSUFFICIENT = "insufficient"


@strawberry.enum
class TransferSourceType(enum.Enum):
    INVENTORY_LOCATION = "INVENTORY_LOCATION"
    STOCK_ITEM = "STOCK_ITEM"
