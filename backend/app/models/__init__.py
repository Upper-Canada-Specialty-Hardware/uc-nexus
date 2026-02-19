from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    pass


# Import all models so Alembic can detect them
from .project import Project, Opening  # noqa: E402, F401
from .hardware import HardwareItem  # noqa: E402, F401
from .purchase_order import PurchaseOrder, POLineItem  # noqa: E402, F401
from .receiving import ReceiveRecord, ReceiveLineItem  # noqa: E402, F401
from .inventory import InventoryLocation  # noqa: E402, F401
from .opening_item import OpeningItem, OpeningItemHardware  # noqa: E402, F401
from .pull_request import PullRequest, PullRequestItem  # noqa: E402, F401
from .shop_assembly import (  # noqa: E402, F401
    ShopAssemblyRequest,
    ShopAssemblyOpening,
    ShopAssemblyOpeningItem,
)
from .shipping import PackingSlip, PackingSlipItem  # noqa: E402, F401
from .notification import Notification  # noqa: E402, F401
