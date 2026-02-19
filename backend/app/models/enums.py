import enum


class Classification(str, enum.Enum):
    SITE_HARDWARE = "Site_Hardware"
    SHOP_HARDWARE = "Shop_Hardware"


class HardwareItemState(str, enum.Enum):
    IN_PO = "In_PO"


class POStatus(str, enum.Enum):
    DRAFT = "Draft"
    ORDERED = "Ordered"
    PARTIALLY_RECEIVED = "Partially_Received"
    CLOSED = "Closed"
    CANCELLED = "Cancelled"


class PullRequestSource(str, enum.Enum):
    SHOP_ASSEMBLY = "Shop_Assembly"
    SHIPPING_OUT = "Shipping_Out"


class PullRequestStatus(str, enum.Enum):
    PENDING = "Pending"
    IN_PROGRESS = "In_Progress"
    COMPLETED = "Completed"
    CANCELLED = "Cancelled"


class PullRequestItemType(str, enum.Enum):
    LOOSE = "Loose"
    OPENING_ITEM = "Opening_Item"


class OpeningItemState(str, enum.Enum):
    IN_INVENTORY = "In_Inventory"
    SHIP_READY = "Ship_Ready"
    SHIPPED_OUT = "Shipped_Out"


class ShopAssemblyRequestStatus(str, enum.Enum):
    PENDING = "Pending"
    APPROVED = "Approved"
    REJECTED = "Rejected"


class PullStatus(str, enum.Enum):
    NOT_PULLED = "Not_Pulled"
    PARTIAL = "Partial"
    PULLED = "Pulled"


class AssemblyStatus(str, enum.Enum):
    PENDING = "Pending"
    COMPLETED = "Completed"


class NotificationType(str, enum.Enum):
    PULL_REQUEST_CANCELLED = "pull_request_cancelled"
    PULL_REQUEST_COMPLETED = "pull_request_completed"
    SHOP_ASSEMBLY_REQUEST_REJECTED = "shop_assembly_request_rejected"
    SHIPMENT_COMPLETED = "shipment_completed"
