"""Completion-time correctness guards for shop assembly (#339).

Three things complete_opening now refuses or records that it previously did not:

1. Duplicate completion - a live OpeningItem already exists for this (opening_id, leaf), so
   completing again would mint a second assembled unit for one physical door leaf.
2. All-deficient completion - every checklist item flagged deficient would mint an OpeningItem with
   zero installed hardware, an "assembled" leaf that reads as ship-ready inventory.
3. Replacement-line identity - the PR-REPL line minted for a deficient item now carries the leaf and
   a FK back to the ShopAssemblyOpeningItem that failed.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ConflictError, ValidationError
from app.models.enums import (
    AssemblyStatus,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
)
from app.models.inventory import InventoryLocation
from app.models.opening_item import OpeningItem
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import shop_assembly_repository, warehouse_admin_repository

HINGE = ("HINGE", "HG-G1")
LOCK = ("LOCK", "LK-G1")


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category, code, quantity=0):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=si.id,
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _make_pulled_opening(session, project_id, *, request_number, items, leaf=None, opening_id=None):
    """A COMPLETED SHOP_ASSEMBLY pull request with one PULLED, assigned, still-pending opening.

    `items` is a list of (category, code, qty). Returns (opening, {code: ShopAssemblyOpeningItem}).
    """
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=request_number,
        project_id=project_id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        requested_by="tester",
        completed_at=datetime.utcnow(),
    )
    session.add(pr)
    session.flush()

    opening = ShopAssemblyOpening(
        id=uuid.uuid4(),
        pull_request_id=pr.id,
        opening_id=opening_id or uuid.uuid4(),
        opening_number="A01",
        leaf=leaf,
        pull_status=PullStatus.PULLED,
        assigned_to="assembler",
        assigned_to_user_id="user_1",
        assembly_status=AssemblyStatus.PENDING,
    )
    session.add(opening)
    session.flush()

    sao_items = {}
    for category, code, qty in items:
        sao_item = ShopAssemblyOpeningItem(
            id=uuid.uuid4(),
            shop_assembly_opening_id=opening.id,
            hardware_category=category,
            product_code=code,
            quantity=qty,
        )
        session.add(sao_item)
        sao_items[code] = sao_item
    session.flush()
    return opening, sao_items


def _make_assembled_unit(session, project_id, opening_id, *, leaf, state=OpeningItemState.IN_INVENTORY):
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project_id,
        opening_id=opening_id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number="A01",
        leaf=leaf,
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=state,
    )
    session.add(oi)
    session.flush()
    return oi


# --- 1. duplicate-completion guard -------------------------------------------------------------


def test_completion_refused_when_leaf_already_assembled(db_session):
    """A live OpeningItem for the same (opening_id, leaf) blocks a second completion."""
    project = _make_project(db_session)
    opening_id = uuid.uuid4()
    _make_assembled_unit(db_session, project.id, opening_id, leaf=1)
    opening, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-DUP1",
        items=[(*HINGE, 2)],
        leaf=1,
        opening_id=opening_id,
    )

    with pytest.raises(ConflictError):
        shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)

    # Nothing was minted and the opening stays workable.
    db_session.flush()
    assert opening.assembly_status == AssemblyStatus.PENDING
    minted = db_session.scalars(select(OpeningItem).where(OpeningItem.opening_id == opening_id)).all()
    assert len(minted) == 1


def test_completion_allowed_when_only_the_other_leaf_is_assembled(db_session):
    """Leaf keying (#311): assembling leaf 1 must not block leaf 2 of the same opening."""
    project = _make_project(db_session)
    opening_id = uuid.uuid4()
    _make_assembled_unit(db_session, project.id, opening_id, leaf=1)
    opening, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-DUP2",
        items=[(*HINGE, 2)],
        leaf=2,
        opening_id=opening_id,
    )

    result = shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()
    assert result.leaf == 2
    assert opening.assembly_status == AssemblyStatus.COMPLETED


def test_completion_allowed_when_prior_unit_shipped_out(db_session):
    """SHIPPED_OUT units are not live - the leaf can be assembled again (a replacement build)."""
    project = _make_project(db_session)
    opening_id = uuid.uuid4()
    _make_assembled_unit(db_session, project.id, opening_id, leaf=1, state=OpeningItemState.SHIPPED_OUT)
    opening, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-DUP3",
        items=[(*HINGE, 2)],
        leaf=1,
        opening_id=opening_id,
    )

    result = shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()
    assert result.state == OpeningItemState.IN_INVENTORY


def test_legacy_null_leaf_unit_only_blocks_a_null_leaf_completion(db_session):
    """Legacy whole-opening units carry a null leaf and match only a null-leaf work unit."""
    project = _make_project(db_session)
    opening_id = uuid.uuid4()
    _make_assembled_unit(db_session, project.id, opening_id, leaf=None)

    leafed, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-DUP4",
        items=[(*HINGE, 2)],
        leaf=1,
        opening_id=opening_id,
    )
    shop_assembly_repository.complete_opening(db_session, leafed.id, None, None, None)
    db_session.flush()

    legacy, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-DUP5",
        items=[(*HINGE, 2)],
        leaf=None,
        opening_id=opening_id,
    )
    with pytest.raises(ConflictError):
        shop_assembly_repository.complete_opening(db_session, legacy.id, None, None, None)


def test_duplicate_guard_is_project_scoped(db_session):
    """The same historical opening_id under a different project does not block completion."""
    other_project = _make_project(db_session)
    project = _make_project(db_session)
    opening_id = uuid.uuid4()
    _make_assembled_unit(db_session, other_project.id, opening_id, leaf=1)
    opening, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-DUP6",
        items=[(*HINGE, 2)],
        leaf=1,
        opening_id=opening_id,
    )

    result = shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()
    assert result.project_id == project.id


# --- 2. all-deficient completion ---------------------------------------------------------------


def test_all_deficient_completion_is_refused(db_session):
    """Every item flagged deficient would mint an empty assembled leaf - refuse the whole call."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1])
    opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-ALLDEF",
        items=[(*HINGE, 1), (*LOCK, 1)],
        leaf=1,
    )

    with pytest.raises(ValidationError):
        shop_assembly_repository.complete_opening(
            db_session,
            opening.id,
            None,
            None,
            None,
            item_results=[
                shop_assembly_repository.OpeningItemResult(sao[HINGE[1]].id, installed=False, deficient_reason="bent"),
                shop_assembly_repository.OpeningItemResult(sao[LOCK[1]].id, installed=False, deficient_reason="seized"),
            ],
            completed_by="assembler",
        )
    db_session.flush()

    # The opening stays pending, no assembled unit exists...
    assert opening.assembly_status == AssemblyStatus.PENDING
    assert opening.completed_at is None
    assert db_session.scalars(select(OpeningItem).where(OpeningItem.opening_id == opening.opening_id)).first() is None

    # ...and no deficiency was recorded: the refusal happens before any unit is returned to
    # inventory or any PR-REPL line is appended, so the call fails whole.
    assert (
        db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-ALLDEF")).first()
        is None
    )
    db_session.refresh(il)
    assert il.quantity == 0
    assert il.deficient_quantity == 0


def test_partially_deficient_completion_still_succeeds(db_session):
    """One installed item is enough - the guard only fires when nothing at all is installed."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1])
    opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-PARTDEF",
        items=[(*HINGE, 1), (*LOCK, 1)],
        leaf=1,
    )

    result = shop_assembly_repository.complete_opening(
        db_session,
        opening.id,
        None,
        None,
        None,
        item_results=[
            shop_assembly_repository.OpeningItemResult(sao[HINGE[1]].id, installed=True),
            shop_assembly_repository.OpeningItemResult(sao[LOCK[1]].id, installed=False, deficient_reason="seized"),
        ],
        completed_by="assembler",
    )
    db_session.flush()
    assert result.state == OpeningItemState.IN_INVENTORY


def test_opening_with_no_items_still_completes(db_session):
    """The guard is 'nothing installed out of something', not 'nothing installed'."""
    project = _make_project(db_session)
    opening, _ = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-NOITEMS",
        items=[],
        leaf=1,
    )

    result = shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()
    assert result.state == OpeningItemState.IN_INVENTORY
    assert opening.assembly_status == AssemblyStatus.COMPLETED


# --- 3. replacement-line identity --------------------------------------------------------------


def test_replacement_pull_line_carries_leaf_and_source_item(db_session):
    """#339: the PR-REPL line is stamped with the leaf and the deficient ShopAssemblyOpeningItem."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=LOCK[0], code=LOCK[1])
    opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-REPL",
        items=[(*HINGE, 1), (*LOCK, 1)],
        leaf=2,
    )

    shop_assembly_repository.complete_opening(
        db_session,
        opening.id,
        None,
        None,
        None,
        item_results=[
            shop_assembly_repository.OpeningItemResult(sao[HINGE[1]].id, installed=True),
            shop_assembly_repository.OpeningItemResult(sao[LOCK[1]].id, installed=False, deficient_reason="seized"),
        ],
        completed_by="assembler",
    )
    db_session.flush()

    repl = db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-REPL")).first()
    assert repl is not None
    lines = list(db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == repl.id)).all())
    assert len(lines) == 1
    line = lines[0]
    assert line.item_type == PullRequestItemType.LOOSE
    assert line.product_code == LOCK[1]
    assert line.opening_number == "A01"
    # Identity restored on the replacement tag: which leaf, and which checklist item it replaces.
    assert line.leaf == 2
    assert line.sa_opening_item_id == sao[LOCK[1]].id
