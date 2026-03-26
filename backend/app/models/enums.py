import enum


class Classification(str, enum.Enum):
    SITE_HARDWARE = "SITE_HARDWARE"
    SHOP_HARDWARE = "SHOP_HARDWARE"


class HardwareItemState(str, enum.Enum):
    IN_PO = "IN_PO"


class POStatus(str, enum.Enum):
    DRAFT = "DRAFT"
    ORDERED = "ORDERED"
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


class OpeningItemState(str, enum.Enum):
    IN_INVENTORY = "IN_INVENTORY"
    SHIP_READY = "SHIP_READY"
    SHIPPED_OUT = "SHIPPED_OUT"


class ShopAssemblyRequestStatus(str, enum.Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class PullStatus(str, enum.Enum):
    NOT_PULLED = "NOT_PULLED"
    PARTIAL = "PARTIAL"
    PULLED = "PULLED"


class AssemblyStatus(str, enum.Enum):
    PENDING = "PENDING"
    COMPLETED = "COMPLETED"


class PODocumentType(str, enum.Enum):
    PO_DOCUMENT = "PO_DOCUMENT"
    VENDOR_ACKNOWLEDGEMENT = "VENDOR_ACKNOWLEDGEMENT"
    MISCELLANEOUS = "MISCELLANEOUS"


class NotificationType(str, enum.Enum):
    PULL_REQUEST_CANCELLED = "PULL_REQUEST_CANCELLED"
    PULL_REQUEST_COMPLETED = "PULL_REQUEST_COMPLETED"
    SHOP_ASSEMBLY_REQUEST_REJECTED = "SHOP_ASSEMBLY_REQUEST_REJECTED"
    SHIPMENT_COMPLETED = "SHIPMENT_COMPLETED"
