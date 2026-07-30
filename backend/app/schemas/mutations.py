"""Root Mutation type - thin composition of the per-domain mutation classes.

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

from .buyer import BuyerMutations
from .gp_outbox import GpOutboxMutations
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
    BuyerMutations,
    GpOutboxMutations,
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
