from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so Alembic can detect them
from .audit_log import InventoryAuditLog  # noqa: E402, F401
from .buyer_assignment import BuyerAssignment  # noqa: E402, F401
from .deficiency_review import DeficiencyReview  # noqa: E402, F401
from .gp_outbox import GpWriteOutbox  # noqa: E402, F401
from .gp_write import GpWriteIdempotency  # noqa: E402, F401
from .hardware import HardwareItem  # noqa: E402, F401
from .inventory import InventoryLocation  # noqa: E402, F401
from .inventory_reservation import InventoryReservation  # noqa: E402, F401
from .manufacturer_vendor_map import ManufacturerVendorMap  # noqa: E402, F401
from .notification import Notification  # noqa: E402, F401
from .opening_item import OpeningItem, OpeningItemHardware  # noqa: E402, F401
from .po_document_settings import PODocumentSettings  # noqa: E402, F401
from .project import Opening, Project  # noqa: E402, F401
from .project_excluded_item import ProjectExcludedItem  # noqa: E402, F401
from .pull_pick_line import PullPickLine  # noqa: E402, F401
from .pull_request import PullRequest, PullRequestItem  # noqa: E402, F401
from .purchase_order import PODocument, PODocumentData, POLineItem, PurchaseOrder  # noqa: E402, F401
from .receive_decision import ReceiveDecision  # noqa: E402, F401
from .receive_draft import ReceiveDraft, ReceiveDraftLineItem  # noqa: E402, F401
from .receiving import ReceiveLineItem, ReceiveRecord  # noqa: E402, F401
from .relay_install import RelayInstall  # noqa: E402, F401
from .shipment_container import (  # noqa: E402, F401
    ShipmentContainer,
    ShipmentContainerItem,
)
from .shipment_method import ShipmentMethod  # noqa: E402, F401
from .shipping import (  # noqa: E402, F401
    PackingSlip,
    PackingSlipItem,
    ShipmentReturn,
    ShipmentReturnItem,
)
from .shipping_out_request import (  # noqa: E402, F401
    ShippingOutRequest,
    ShippingOutRequestItem,
)
from .shop_assembly import (  # noqa: E402, F401
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ShopAssemblyRequest,
)
from .stock_item import StockItem  # noqa: E402, F401
from .vendor import Vendor  # noqa: E402, F401
from .warehouse import Warehouse  # noqa: E402, F401
