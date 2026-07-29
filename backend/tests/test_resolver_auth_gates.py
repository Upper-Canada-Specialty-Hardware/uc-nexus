"""Gated resolvers call their gate before they act (#345, extended to the admin surface by #415).

Auth in this codebase is **opt-in per resolver** (CLAUDE.md): there is no middleware to catch a
resolver that forgets, and `get_context` only stashes the request. That makes a dropped
`require_user(info)` invisible - the resolver keeps working, it just works for anonymous callers
too, which is exactly how `reportDeficiencyAtAssembly` came to mint replacement pull requests and
write project inventory with no session at all.

These are pin tests, not behaviour tests. Each one replaces the gate with something that raises a
sentinel and asserts the sentinel comes back out: if the gate runs, the call cannot proceed, so no
database is needed and nothing about the resolver body is asserted. A refactor that drops a gate
makes the resolver return (or fail differently) and the test goes red on that resolver by name.

`shopAssemblyMembers` and the manager branch of `assignOpenings` are role-gated rather than
user-gated; both gates are pinned.

This file pins gates one at a time and proves the gate runs *first*, which is what a monkeypatched
sentinel can show and a source scan cannot. It says nothing about resolvers nobody thought to list -
that is `test_resolver_gate_completeness.py`, which walks every resolver in `app/schemas/` and fails
on any that never asks. The two are complements: this one is depth, that one is coverage.
"""

import uuid

import pytest

from app.schemas import admin as admin_module
from app.schemas import dashboard as dashboard_module
from app.schemas import gp_outbox as gp_outbox_module
from app.schemas import relay as relay_module
from app.schemas import shop_assembly as shop_assembly_module
from app.schemas import stock as stock_module
from app.schemas import user as user_module
from app.schemas import vendor as vendor_module
from app.schemas import warehouse as warehouse_module
from app.schemas.admin import AdminQueries
from app.schemas.dashboard import DashboardQueries
from app.schemas.enums import DeficiencyResolution
from app.schemas.gp_outbox import GpOutboxMutations, GpOutboxQueries
from app.schemas.inputs import (
    AssignOpeningsInput,
    CompleteOpeningInput,
    CreateVendorInput,
    CreateWarehouseInput,
    InstallReplacementInput,
    OverrideInventoryQuantityInput,
    PickLineInput,
    RecordAssemblyProgressInput,
    ReportDeficiencyAtAssemblyInput,
    ReportInventoryDeficiencyInput,
    ReportStockDeficiencyInput,
    ResolveDeficiencyInput,
    UpdateVendorInput,
    UpdateWarehouseInput,
)
from app.schemas.relay import RelayMutations, RelayQueries
from app.schemas.shop_assembly import ShopAssemblyMutations, ShopAssemblyQueries
from app.schemas.stock import StockMutations
from app.schemas.user import UserMutations, UserQueries
from app.schemas.vendor import VendorMutations
from app.schemas.warehouse import WarehouseMutations, WarehouseQueries


class _GateReached(Exception):
    """Raised by the stubbed gate. Seeing it means the resolver asked before it acted."""


class FakeInfo:
    def __init__(self, request=None):
        self.context = {"request": request}


def _id() -> str:
    return str(uuid.uuid4())


# (label, module the resolver resolves its gate from, callable taking no args)
_USER_GATED = [
    ("assembleList", shop_assembly_module, lambda: ShopAssemblyQueries().assemble_list(FakeInfo())),
    ("myWork", shop_assembly_module, lambda: ShopAssemblyQueries().my_work(FakeInfo(), "user_1")),
    ("replacementWork", shop_assembly_module, lambda: ShopAssemblyQueries().replacement_work(FakeInfo())),
    (
        "shopAssemblyRequests",
        shop_assembly_module,
        lambda: ShopAssemblyQueries().shop_assembly_requests(FakeInfo()),
    ),
    (
        "assemblyPipelineSummaries",
        shop_assembly_module,
        lambda: ShopAssemblyQueries().assembly_pipeline_summaries(FakeInfo()),
    ),
    (
        "assemblyPipeline",
        shop_assembly_module,
        lambda: ShopAssemblyQueries().assembly_pipeline(FakeInfo(), _id()),
    ),
    (
        "acceptShopAssemblyRequest",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().accept_shop_assembly_request(FakeInfo(), _id(), "acceptor"),
    ),
    (
        "rejectShopAssemblyRequest",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().reject_shop_assembly_request(FakeInfo(), _id(), "rejector"),
    ),
    (
        "reopenShopAssemblyRequest",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().reopen_shop_assembly_request(FakeInfo(), _id()),
    ),
    (
        "assignOpenings",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().assign_openings(
            FakeInfo(),
            AssignOpeningsInput(opening_ids=[_id()], assigned_to_user_id="user_1", assigned_to="Someone"),
        ),
    ),
    (
        "removeOpeningFromUser",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().remove_opening_from_user(FakeInfo(), _id()),
    ),
    (
        "recordAssemblyProgress",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().record_assembly_progress(
            FakeInfo(), RecordAssemblyProgressInput(opening_id=_id(), items=[])
        ),
    ),
    (
        "installReplacement",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().install_replacement(
            FakeInfo(), InstallReplacementInput(shop_assembly_opening_item_id=_id(), quantity=1)
        ),
    ),
    (
        "completeOpening",
        shop_assembly_module,
        lambda: ShopAssemblyMutations().complete_opening(FakeInfo(), CompleteOpeningInput(opening_id=_id())),
    ),
    (
        "reportInventoryDeficiency",
        stock_module,
        lambda: StockMutations().report_inventory_deficiency(
            FakeInfo(), ReportInventoryDeficiencyInput(inventory_location_id=_id(), quantity=1)
        ),
    ),
    (
        "reportStockDeficiency",
        stock_module,
        lambda: StockMutations().report_stock_deficiency(
            FakeInfo(), ReportStockDeficiencyInput(stock_item_id=_id(), quantity=1)
        ),
    ),
    (
        "reportDeficiencyAtAssembly",
        stock_module,
        lambda: StockMutations().report_deficiency_at_assembly(
            FakeInfo(), ReportDeficiencyAtAssemblyInput(shop_assembly_opening_item_id=_id(), quantity=1)
        ),
    ),
    (
        "resolveDeficiency",
        stock_module,
        lambda: StockMutations().resolve_deficiency(
            FakeInfo(),
            ResolveDeficiencyInput(
                inventory_location_id=_id(),
                resolution=DeficiencyResolution.REPAIR,
                quantity=1,
                reviewed_by="reviewer",
            ),
        ),
    ),
    # The pick (#367). confirmPick writes inventory; the other three attribute a user action or
    # expose one project's per-location stock, so all four are gated for the same reasons the
    # staging and cancel mutations next to them are.
    (
        "pullPickSheet",
        warehouse_module,
        lambda: WarehouseQueries().pull_pick_sheet(FakeInfo(), _id()),
    ),
    (
        "startPullRequestPick",
        warehouse_module,
        lambda: WarehouseMutations().start_pull_request_pick(FakeInfo(), _id(), "picker"),
    ),
    (
        "savePickDraft",
        warehouse_module,
        lambda: WarehouseMutations().save_pick_draft(
            FakeInfo(),
            _id(),
            [PickLineInput(hardware_category="HINGE", product_code="HG-100", inventory_location_id=_id(), quantity=1)],
            "picker",
        ),
    ),
    (
        "confirmPick",
        warehouse_module,
        lambda: WarehouseMutations().confirm_pick(
            FakeInfo(),
            _id(),
            [PickLineInput(hardware_category="HINGE", product_code="HG-100", inventory_location_id=_id(), quantity=1)],
            "picker",
        ),
    ),
    (
        "setPullItemFetched",
        warehouse_module,
        lambda: WarehouseMutations().set_pull_item_fetched(FakeInfo(), _id(), True, "picker"),
    ),
]


# Admin-only resolvers. The adopt window (#353 PR B) deliberately weakens the /relay-link auth
# boundary while it is open, so "is this actually admin-gated" is a security property, not a nicety.
_ADMIN_GATED = [
    ("relayAdoptWindow", relay_module, lambda: RelayQueries().relay_adopt_window(FakeInfo())),
    ("armRelayAdopt", relay_module, lambda: RelayMutations().arm_relay_adopt(FakeInfo(), _id())),
    ("disarmRelayAdopt", relay_module, lambda: RelayMutations().disarm_relay_adopt(FakeInfo())),
    # #366: deleting an install revokes a relay credential outright, so the gate is the whole
    # protection - there is nothing downstream to catch a non-admin caller.
    ("deleteRelayInstall", relay_module, lambda: RelayMutations().delete_relay_install(FakeInfo(), _id())),
    # #353 PR E: retrying an `ambiguous` queued write can duplicate a GP posting, and cancelling one
    # abandons work somebody has already done. Both are admin-only.
    (
        "retryGpOutboxEntry",
        gp_outbox_module,
        lambda: GpOutboxMutations().retry_gp_outbox_entry(FakeInfo(), _id()),
    ),
    (
        "cancelGpOutboxEntry",
        gp_outbox_module,
        lambda: GpOutboxMutations().cancel_gp_outbox_entry(FakeInfo(), _id()),
    ),
    # #415. All four user.py resolvers shipped with no gate at all. `updateUserRoles` is the one that
    # matters most: it grants Admin/Manager, the role every other entry in this list is gated on, so
    # an ungated copy is a self-service escalation into all of them. `users` returns every account's
    # email, roles and GP buyer id.
    ("users", user_module, lambda: UserQueries().users(FakeInfo())),
    (
        "updateUserRoles",
        user_module,
        lambda: UserMutations().update_user_roles(FakeInfo(), "user_1", ["Admin/Manager"]),
    ),
    (
        "updateUserName",
        user_module,
        lambda: UserMutations().update_user_name(FakeInfo(), "user_1", "First", "Last"),
    ),
    (
        "updateUserGpBuyerId",
        user_module,
        lambda: UserMutations().update_user_gp_buyer_id(FakeInfo(), "user_1", "donr"),
    ),
    # #415 sweep: the rest of the admin-only surface, all of it previously ungated. The warehouse and
    # vendor writes are the ones with teeth - an anonymous caller could delete a warehouse, rewrite an
    # inventory row's quantity outright, or merge every item at one location into another.
    (
        "openingHardwareStatus",
        admin_module,
        lambda: AdminQueries().opening_hardware_status(FakeInfo()),
    ),
    ("adminStats", dashboard_module, lambda: DashboardQueries().admin_stats(FakeInfo())),
    (
        "createVendor",
        vendor_module,
        lambda: VendorMutations().create_vendor(FakeInfo(), CreateVendorInput(name="V")),
    ),
    (
        "updateVendor",
        vendor_module,
        lambda: VendorMutations().update_vendor(FakeInfo(), _id(), UpdateVendorInput(name="V")),
    ),
    ("deleteVendor", vendor_module, lambda: VendorMutations().delete_vendor(FakeInfo(), _id())),
    (
        "locationDuplicates",
        warehouse_module,
        lambda: WarehouseQueries().location_duplicates(FakeInfo()),
    ),
    (
        "overrideInventoryQuantity",
        warehouse_module,
        lambda: WarehouseMutations().override_inventory_quantity(
            FakeInfo(),
            OverrideInventoryQuantityInput(inventory_location_id=_id(), new_quantity=1, reason_text="r"),
        ),
    ),
    (
        "mergeLocations",
        warehouse_module,
        lambda: WarehouseMutations().merge_locations(FakeInfo(), "A", "1", "1", "B", "2", "2"),
    ),
    (
        "createWarehouse",
        warehouse_module,
        lambda: WarehouseMutations().create_warehouse(FakeInfo(), CreateWarehouseInput(name="W", code="W1")),
    ),
    (
        "updateWarehouse",
        warehouse_module,
        lambda: WarehouseMutations().update_warehouse(FakeInfo(), _id(), UpdateWarehouseInput(name="W")),
    ),
    (
        "deleteWarehouse",
        warehouse_module,
        lambda: WarehouseMutations().delete_warehouse(FakeInfo(), _id()),
    ),
]

# Any signed-in user; the PO and receiving lists read the queue to show pending chips.
_OUTBOX_USER_GATED = [
    ("gpOutboxSummary", gp_outbox_module, lambda: GpOutboxQueries().gp_outbox_summary(FakeInfo())),
    ("gpOutbox", gp_outbox_module, lambda: GpOutboxQueries().gp_outbox(FakeInfo())),
]


@pytest.mark.parametrize("label, module, call", _USER_GATED, ids=[row[0] for row in _USER_GATED])
def test_resolver_requires_a_signed_in_user(label, module, call, monkeypatch):
    def _gate(info):
        raise _GateReached(label)

    monkeypatch.setattr(module, "require_user", _gate)

    with pytest.raises(_GateReached):
        call()


@pytest.mark.parametrize("label, module, call", _ADMIN_GATED, ids=[row[0] for row in _ADMIN_GATED])
def test_resolver_requires_an_admin(label, module, call, monkeypatch):
    def _gate(info):
        raise _GateReached(label)

    monkeypatch.setattr(module, "require_admin", _gate)

    with pytest.raises(_GateReached):
        call()


@pytest.mark.parametrize("label, module, call", _OUTBOX_USER_GATED, ids=[row[0] for row in _OUTBOX_USER_GATED])
def test_outbox_read_requires_a_signed_in_user(label, module, call, monkeypatch):
    def _gate(info):
        raise _GateReached(label)

    monkeypatch.setattr(module, "require_user", _gate)

    with pytest.raises(_GateReached):
        call()


def test_shop_assembly_members_requires_the_manager_role(monkeypatch):
    def _gate(info, role):
        raise _GateReached(role)

    monkeypatch.setattr(shop_assembly_module, "require_role", _gate)

    with pytest.raises(_GateReached):
        ShopAssemblyQueries().shop_assembly_members(FakeInfo())


def test_assigning_to_another_user_requires_the_manager_role(monkeypatch):
    """The one gate that is conditional: self-assignment is open, assigning somebody else is not."""

    def _role_gate(info, role):
        raise _GateReached(role)

    monkeypatch.setattr(shop_assembly_module, "require_user", lambda info: {"user_id": "caller"})
    monkeypatch.setattr(shop_assembly_module, "require_role", _role_gate)

    with pytest.raises(_GateReached):
        ShopAssemblyMutations().assign_openings(
            FakeInfo(),
            AssignOpeningsInput(opening_ids=[_id()], assigned_to_user_id="somebody_else", assigned_to="Other"),
        )
