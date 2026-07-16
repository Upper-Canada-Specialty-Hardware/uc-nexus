"""Root Mutation type - thin composition of the per-domain mutation classes.

Resolver implementations live in the domain modules (schemas/po.py, schemas/warehouse.py, ...),
mirroring app/repositories/. DTO builders live in schemas/converters.py.
"""

import strawberry

from .imports import ImportMutations
from .notification import NotificationMutations
from .po import POMutations
from .project import ProjectMutations
from .relay import RelayMutations
from .shipping import ShippingMutations
from .shop_assembly import ShopAssemblyMutations
from .stock import StockMutations
from .user import UserMutations
from .vendor import VendorMutations
from .warehouse import WarehouseMutations


@strawberry.type
class Mutation(
    ImportMutations,
    NotificationMutations,
    POMutations,
    ProjectMutations,
    RelayMutations,
    ShippingMutations,
    ShopAssemblyMutations,
    StockMutations,
    UserMutations,
    VendorMutations,
    WarehouseMutations,
):
    pass
