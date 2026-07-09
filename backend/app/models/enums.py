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
    SHIPMENT_COMPLETED = "SHIPMENT_COMPLETED"
    # PO "couldn't be fulfilled - backfill needed" signal from the inventory-sufficiency gates (#224).
    # Carries the per-combo shortfall detail in its message.
    INVENTORY_SHORTFALL = "INVENTORY_SHORTFALL"


class AuditEntityType(str, enum.Enum):
    INVENTORY_LOCATION = "INVENTORY_LOCATION"
    OPENING_ITEM = "OPENING_ITEM"
    STOCK_ITEM = "STOCK_ITEM"


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
