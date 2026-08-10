"""Root Query type - thin composition of the per-domain query classes.

Resolver implementations live in the domain modules (schemas/po.py, schemas/warehouse.py, ...),
mirroring app/repositories/. DTO builders live in schemas/converters.py.

Every field on this type is a ROOT field, and every root field is authorized from
ROOT_FIELD_POLICY in app/auth_policy.py - checked by the schema extension in main.py before the
resolver runs, not by a line in the body (#423). A field with no entry there, and no place on the
OPEN_OPERATIONS allowlist, is refused. So adding a resolver below means adding its policy entry;
forgetting breaks the field rather than opening it, and `tests/test_resolver_gate_completeness.py`
fails on it either way.
"""

import strawberry

from .buyer import BuyerQueries
from .custom_items import CustomItemQueries
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
from .warehouse import WarehouseQueries


@strawberry.type
class Query(
    BuyerQueries,
    CustomItemQueries,
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
    WarehouseQueries,
):
    pass
