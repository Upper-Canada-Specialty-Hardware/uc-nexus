"""Root Query type - thin composition of the per-domain query classes.

Resolver implementations live in the domain modules (schemas/po.py, schemas/warehouse.py, ...),
mirroring app/repositories/. DTO builders live in schemas/converters.py.
"""

import strawberry

from .admin import AdminQueries
from .buyer import BuyerQueries
from .dashboard import DashboardQueries
from .gp_outbox import GpOutboxQueries
from .imports import ImportQueries
from .notification import NotificationQueries
from .po import POQueries
from .project import ProjectQueries
from .relay import RelayQueries
from .shipping import ShippingQueries
from .shop_assembly import ShopAssemblyQueries
from .stock import StockQueries
from .user import UserQueries
from .vendor import VendorQueries
from .warehouse import WarehouseQueries


@strawberry.type
class Query(
    AdminQueries,
    BuyerQueries,
    DashboardQueries,
    GpOutboxQueries,
    ImportQueries,
    NotificationQueries,
    POQueries,
    ProjectQueries,
    RelayQueries,
    ShippingQueries,
    ShopAssemblyQueries,
    StockQueries,
    UserQueries,
    VendorQueries,
    WarehouseQueries,
):
    pass
