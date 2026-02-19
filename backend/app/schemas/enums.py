import enum

import strawberry

from app.models.enums import (
    Classification as ClassificationDB,
    HardwareItemState as HardwareItemStateDB,
    POStatus as POStatusDB,
    PullRequestSource as PullRequestSourceDB,
    PullRequestStatus as PullRequestStatusDB,
    PullRequestItemType as PullRequestItemTypeDB,
    OpeningItemState as OpeningItemStateDB,
    ShopAssemblyRequestStatus as ShopAssemblyRequestStatusDB,
    PullStatus as PullStatusDB,
    AssemblyStatus as AssemblyStatusDB,
    NotificationType as NotificationTypeDB,
)

# Wrap DB enums for Strawberry GraphQL
Classification = strawberry.enum(ClassificationDB)
HardwareItemState = strawberry.enum(HardwareItemStateDB)
POStatus = strawberry.enum(POStatusDB)
PullRequestSource = strawberry.enum(PullRequestSourceDB)
PullRequestStatus = strawberry.enum(PullRequestStatusDB)
PullRequestItemType = strawberry.enum(PullRequestItemTypeDB)
OpeningItemState = strawberry.enum(OpeningItemStateDB)
ShopAssemblyRequestStatus = strawberry.enum(ShopAssemblyRequestStatusDB)
PullStatus = strawberry.enum(PullStatusDB)
AssemblyStatus = strawberry.enum(AssemblyStatusDB)
NotificationType = strawberry.enum(NotificationTypeDB)


# GraphQL-only enums (not stored in database)
@strawberry.enum
class ReconciliationStatus(enum.Enum):
    AVAILABLE = "available"
    PARTIAL = "partial"
    NOT_AVAILABLE = "not_available"


@strawberry.enum
class ApproveOutcome(enum.Enum):
    APPROVED = "approved"
    CANCELLED = "cancelled"
