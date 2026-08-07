"""Tests for the assembly deficiency path (#225, reworked for #340).

Flagging a deficient unit used to be an argument to complete_opening. It is now its own act, recorded
through record_assembly_progress the moment the defect is found at the bench: the unit is returned to
project inventory flagged deficient (quantity AND deficient_quantity both bumped on an existing row)
and a PR-REPL replacement pull is appended straight away, so the warehouse can start sourcing the
replacement while the leaf is still being built.

Completion then only snapshots what was actually installed. These tests cover the deficiency half of
that split; the progress and gating half is in test_assembly_progress.py.
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

Update = shop_assembly_repository.AssemblyProgressUpdate


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
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _make_pulled_opening(session, project_id, *, request_number, items):
    """A completed SHOP_ASSEMBLY PR with a single PULLED opening (assembly PENDING, assigned).

    `items` is a list of (category, code, qty). Mirrors the import: one LOOSE PR item and one
    ShopAssemblyOpeningItem per line, all at zero recorded progress. Returns (pr, opening, {code: item}).
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
        assigned_to_user_id="user_1",
        assembly_status=AssemblyStatus.PENDING,
    )
    session.add(opening)
    session.flush()

    sao_items = {}
    for category, code, qty, *rest in items:
        allocated = rest[0] if rest else qty
        session.add(
            PullRequestItem(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                item_type=PullRequestItemType.LOOSE,
                opening_number="A01",
                hardware_category=category,
                product_code=code,
                requested_quantity=allocated,
            )
        )
        sao_item = ShopAssemblyOpeningItem(
            id=uuid.uuid4(),
            shop_assembly_opening_id=opening.id,
            hardware_category=category,
            product_code=code,
            quantity=qty,
            allocated_quantity=allocated,
        )
        session.add(sao_item)
        sao_items[code] = sao_item
    session.flush()
    return pr, opening, sao_items


def _installed_hardware(session, opening_item_id):
    return list(
        session.scalars(select(OpeningItemHardware).where(OpeningItemHardware.opening_item_id == opening_item_id)).all()
    )


def test_deficiency_returns_unit_and_mints_replacement_before_completion(db_session):
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

    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            Update(sao[INSTALLED[1]].id, installed_quantity=1),
            Update(sao[DEFICIENT[1]].id, flag_deficient_quantity=1, deficient_reason="bent tab"),
        ],
        performed_by="assembler",
    )
    db_session.flush()

    # The deficient unit is returned to inventory flagged deficient (both counts bumped together),
    # and the replacement pull exists BEFORE the leaf is finished - the point of moving it here.
    def_il = db_session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id,
            InventoryLocation.product_code == DEFICIENT[1],
        )
    ).first()
    assert def_il.quantity == 1
    assert def_il.deficient_quantity == 1

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

    # ...and the opening is now in progress, not pending.
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS

    result = shop_assembly_repository.complete_opening(db_session, opening.id, completed_by="assembler")
    db_session.flush()

    # Assembled leaf returns to inventory carrying only what was installed.
    assert result.state == OpeningItemState.IN_INVENTORY
    # #498: completion no longer places the leaf. It lands unlocated and the warehouse assigns a
    # real warehouse and bin from the put-away queue.
    assert result.aisle is None and result.row is None and result.bay is None
    hw = _installed_hardware(db_session, result.id)
    assert {h.product_code for h in hw} == {INSTALLED[1]}

    db_session.refresh(opening)
    assert opening.assembly_status == AssemblyStatus.COMPLETED
    assert opening.completed_at is not None


def test_no_deficiency_means_no_replacement_pull(db_session):
    """Installing everything mints nothing extra - a replacement PR only exists if a defect is found."""
    project = _make_project(db_session)
    _, opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK2",
        items=[(*INSTALLED, 2), (*DEFICIENT, 1)],
    )

    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            Update(sao[INSTALLED[1]].id, installed_quantity=2),
            Update(sao[DEFICIENT[1]].id, installed_quantity=1),
        ],
        performed_by="assembler",
    )
    result = shop_assembly_repository.complete_opening(db_session, opening.id)
    db_session.flush()

    hw = _installed_hardware(db_session, result.id)
    assert {h.product_code: h.quantity for h in hw} == {INSTALLED[1]: 2, DEFICIENT[1]: 1}

    repl = db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-CHK2")).first()
    assert repl is None


def test_progress_item_must_belong_to_opening(db_session):
    project = _make_project(db_session)
    _, opening, _sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK3",
        items=[(*INSTALLED, 1)],
    )

    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session,
            opening.id,
            [Update(uuid.uuid4(), flag_deficient_quantity=1, deficient_reason="x")],
        )


def test_deficiency_creates_inventory_row_when_deleted(db_session):
    """#227(2): a deficient flag still lands when the source inventory row was hard-deleted.

    Simulates a replace-schedule re-upload that removed the InventoryLocation row after the unit
    was pulled. report_deficiency_at_assembly re-materializes the row instead of aborting, so the
    rest of the leaf can still be built and completed.
    """
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, category=DEFICIENT[0], code=DEFICIENT[1], quantity=0)
    db_session.delete(il)
    db_session.flush()

    _, opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK4",
        items=[(*INSTALLED, 1), (*DEFICIENT, 1)],
    )

    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            Update(sao[INSTALLED[1]].id, installed_quantity=1),
            Update(sao[DEFICIENT[1]].id, flag_deficient_quantity=1, deficient_reason="bent tab"),
        ],
        performed_by="assembler",
    )
    result = shop_assembly_repository.complete_opening(db_session, opening.id, completed_by="assembler")
    db_session.flush()

    # Installed item is still snapshotted despite the missing deficient-product row.
    hw = _installed_hardware(db_session, result.id)
    assert {h.product_code for h in hw} == {INSTALLED[1]}

    # A fresh inventory row was materialized for the returned deficient unit (available 0).
    def_il = db_session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id,
            InventoryLocation.product_code == DEFICIENT[1],
        )
    ).first()
    assert def_il is not None
    assert def_il.quantity == 1
    assert def_il.deficient_quantity == 1
    assert def_il.stock_item_id is not None

    repl = db_session.scalars(select(PullRequest).where(PullRequest.request_number == "PR-REPL-PR-SA-CHK4")).first()
    assert repl is not None
    assert opening.assembly_status == AssemblyStatus.COMPLETED


def test_deficient_item_requires_reason(db_session):
    """#227(3): a flagged unit with a missing/blank reason is rejected."""
    project = _make_project(db_session)
    _, opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK5",
        items=[(*DEFICIENT, 1)],
    )

    for bad_reason in (None, "   "):
        with pytest.raises(ValidationError):
            shop_assembly_repository.record_assembly_progress(
                db_session,
                opening.id,
                [Update(sao[DEFICIENT[1]].id, flag_deficient_quantity=1, deficient_reason=bad_reason)],
            )


def test_deficient_reason_length_capped(db_session):
    """#227(3): a deficiency reason over 500 characters is rejected."""
    project = _make_project(db_session)
    _, opening, sao = _make_pulled_opening(
        db_session,
        project.id,
        request_number="PR-SA-CHK6",
        items=[(*DEFICIENT, 1)],
    )

    with pytest.raises(ValidationError):
        shop_assembly_repository.record_assembly_progress(
            db_session,
            opening.id,
            [Update(sao[DEFICIENT[1]].id, flag_deficient_quantity=1, deficient_reason="x" * 501)],
        )
