"""Every gated resolver in the shop-assembly and stock modules actually calls its gate (#345).

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
"""

import uuid

import pytest

from app.schemas import shop_assembly as shop_assembly_module
from app.schemas import stock as stock_module
from app.schemas.enums import DeficiencyResolution
from app.schemas.inputs import (
    AssignOpeningsInput,
    CompleteOpeningInput,
    InstallReplacementInput,
    RecordAssemblyProgressInput,
    ReportDeficiencyAtAssemblyInput,
    ReportInventoryDeficiencyInput,
    ReportStockDeficiencyInput,
    ResolveDeficiencyInput,
)
from app.schemas.shop_assembly import ShopAssemblyMutations, ShopAssemblyQueries
from app.schemas.stock import StockMutations


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
]


@pytest.mark.parametrize("label, module, call", _USER_GATED, ids=[row[0] for row in _USER_GATED])
def test_resolver_requires_a_signed_in_user(label, module, call, monkeypatch):
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
