"""Tests for the completion-time deficiency checklist (#225).

complete_opening snapshots only INSTALLED checklist items as OpeningItemHardware. Items flagged
not-installed are returned to project inventory flagged deficient (quantity AND deficient_quantity
both bumped on an existing row) and get a PR-REPL replacement pull appended. An empty checklist
snapshots every item (pre-checklist behaviour). The assembled opening returns to inventory.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.enums import (
    AssemblyStatus,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
)
from app.models.inventory import InventoryLocation
from app.models.opening_item import OpeningItemHardware
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import shop_assembly_repository, warehouse_admin_repository

INSTALLED = ("HINGE", "HG-INST")
DEFICIENT = ("LOCK", "LK-DEF")


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category, code, quantity, deficient=0):
    """A project inventory row (with its backing stock item) for a category/product."""
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
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
        deficient_quantity=deficient,
        aisle="A",
        bay="1",
        bin="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _make_pulled_opening(session, project_id, *, request_number, items):
    """A completed SHOP_ASSEMBLY PR with a single PULLED opening (assembly PENDING, assigned).

    `items` is a list of (category, code, qty). Mirrors the import: one LOOSE PR item and one
    ShopAssemblyOpeningItem per line. Returns (pr, opening, {code: ShopAssemblyOpeningItem}).
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
        opening_id=uuid.uuid4(),
        opening_number="A01",
        building="B1",
        floor="1",
        location="L1",
        pull_status=PullStatus.PULLED,
        assigned_to="assembler",
        assembly_status=AssemblyStatus.PENDING,
    )
    session.add(opening)
    session.flush()

    sao_items = {}
    for category, code, qty in items:
        session.add(
            PullRequestItem(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                item_type=PullRequestItemType.LOOSE,
                opening_number="A01",
                hardware_category=category,
                product_code=code,
                requested_quantity=qty,
            )
        )
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
    return pr, opening, sao_items


def _installed_hardware(session, opening_item_id):
    return list(
        session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == opening_item_id)).all()
    )


def test_completion_snapshots_only_installed_and_flags_deficient(db_session):
    project = _make_project(db_session)
    # Row for the deficient product is at quantity 0, i.e. fully pulled - the deficient unit still
    # has an existing row to be returned onto.
    _seed_inventory(db_session, project.id, category=DEFICIENT[0], code=DEFICIENT[1], quantity=0)
    _, opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK1",
        items=[(*INSTALLED, 1), (*DEFICIENT, 1)],
    )

    result = shop_assembly_repository.complete_opening(
        db_session,
        opening.id,
        "A",
        "2",
        "3",
        item_results=[
            shop_assembly_repository.OpeningItemResult(sao[INSTALLED[1]].id, installed=True),
            shop_assembly_repository.OpeningItemResult(
                sao[DEFICIENT[1]].id, installed=False, deficient_reason="bent tab"
            ),
        ],
        completed_by="assembler",
    )
    db_session.flush()

    # Assembled opening returns to inventory.
    assert result.state == OpeningItemState.IN_INVENTORY
    assert result.aisle == "A" and result.bay == "2" and result.bin == "3"

    # Only the installed item is snapshotted as hardware.
    hw = _installed_hardware(db_session, result.id)
    assert {h.product_code for h in hw} == {INSTALLED[1]}

    # The deficient unit is returned to inventory flagged deficient (both counts bumped together).
    def_il = db_session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id,
            InventoryLocation.product_code == DEFICIENT[1],
        )
    ).first()
    assert def_il.quantity == 1
    assert def_il.deficient_quantity == 1

    # A replacement pull was appended for the deficient product.
    repl = db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-CHK1")).first()
    assert repl is not None
    assert repl.status == PullRequestStatus.PENDING
    repl_items = list(
        db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == repl.id)).all()
    )
    assert len(repl_items) == 1
    assert repl_items[0].product_code == DEFICIENT[1]
    assert repl_items[0].requested_quantity == 1
    assert repl_items[0].opening_number == "A01"

    # Opening is marked completed.
    db_session.refresh(opening)
    assert opening.assembly_status == AssemblyStatus.COMPLETED
    assert opening.completed_at is not None


def test_empty_checklist_snapshots_all_items(db_session):
    project = _make_project(db_session)
    _, opening, _sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK2",
        items=[(*INSTALLED, 2), (*DEFICIENT, 1)],
    )

    result = shop_assembly_repository.complete_opening(db_session, opening.id, None, None, None)
    db_session.flush()

    hw = _installed_hardware(db_session, result.id)
    assert {h.product_code for h in hw} == {INSTALLED[1], DEFICIENT[1]}

    # No replacement pull created when nothing is flagged deficient.
    repl = db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-CHK2")).first()
    assert repl is None


def test_checklist_item_must_belong_to_opening(db_session):
    project = _make_project(db_session)
    _, opening, _sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK3",
        items=[(*INSTALLED, 1)],
    )

    with pytest.raises(ValidationError):
        shop_assembly_repository.complete_opening(
            db_session,
            opening.id,
            None,
            None,
            None,
            item_results=[
                shop_assembly_repository.OpeningItemResult(uuid.uuid4(), installed=False, deficient_reason="x")
            ],
        )
