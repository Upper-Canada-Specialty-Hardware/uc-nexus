from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so Alembic can detect them
from .audit_log import InventoryAuditLog  # noqa: E402, F401
from .hardware import HardwareItem  # noqa: E402, F401
from .inventory import InventoryLocation  # noqa: E402, F401
from .notification import Notification  # noqa: E402, F401
from .opening_item import OpeningItem, OpeningItemHardware  # noqa: E402, F401
from .project import Opening, Project  # noqa: E402, F401
from .project_excluded_item import ProjectExcludedItem  # noqa: E402, F401
from .pull_request import PullRequest, PullRequestItem  # noqa: E402, F401
from .purchase_order import PODocument, POLineItem, PurchaseOrder  # noqa: E402, F401
from .receiving import ReceiveLineItem, ReceiveRecord  # noqa: E402, F401
from .shipping import PackingSlip, PackingSlipItem  # noqa: E402, F401
from .shop_assembly import (  # noqa: E402, F401
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
    ShopAssemblyRequest,
)
from .warehouse_layout import WarehouseAisle, WarehouseBay, WarehouseBin  # noqa: E402, F401
