"""Tests for the two hard inventory-sufficiency gates and the shared helper (#224).

Gate 1: import "Start a Task" (shop assembly) refuses to mint the PR when short.
Gate 2: warehouse approve_pull_request leaves the PR PENDING (not cancelled) when short.
Both notify the PO with an INVENTORY_SHORTFALL signal carrying the shortfall detail.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InventoryShortfallError
from app.models.enums import (
    NotificationType,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.notification import Notification
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, warehouse_admin_repository, warehouse_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity, deficient=0, received_at=None):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
        received_at=received_at or datetime.utcnow(),
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
        received_at=received_at or datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _make_pending_pr(session, project_id, *, needs, request_number=None, source=PullRequestSource.SHOP_ASSEMBLY):
    """A PENDING PR with one LOOSE item per (category, code, qty) in `needs`."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=request_number or f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project_id,
        source=source,
        status=PullRequestStatus.PENDING,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    for category, code, qty in needs:
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
    session.flush()
    return pr


def _po_shortfall_notifs(session, project_id):
    return list(
        session.scalars(
            select(Notification).where(
                Notification.project_id == project_id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
            )
        ).all()
    )


# --- shared helper ---------------------------------------------------------------------------


def test_helper_reports_no_shortfall_when_covered(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)

    result = warehouse_repository.check_inventory_sufficiency(db_session, project.id, [("HINGE", "HG-100", 5)])

    assert result.sufficient
    assert result.shortfalls == []


def test_helper_counts_only_available_units(db_session):
    """available = quantity - deficient_quantity: deficient units cannot cover the request."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5, deficient=3)  # only 2 available

    result = warehouse_repository.check_inventory_sufficiency(db_session, project.id, [("HINGE", "HG-100", 5)])

    assert not result.sufficient
    assert len(result.shortfalls) == 1
    s = result.shortfalls[0]
    assert (s.hardware_category, s.product_code) == ("HINGE", "HG-100")
    assert (s.requested, s.available, s.short) == (5, 2, 3)


def test_helper_aggregates_duplicate_combos(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)

    # 2 + 2 = 4 requested for the same combo, only 3 available -> short 1
    result = warehouse_repository.check_inventory_sufficiency(
        db_session, project.id, [("HINGE", "HG-100", 2), ("HINGE", "HG-100", 2)]
    )

    assert len(result.shortfalls) == 1
    assert result.shortfalls[0].short == 1


# --- gate 1: import "Start a Task" -----------------------------------------------------------


def _finalize_shop_assembly(session, project, *, code, qty):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [
                {
                    "opening_number": "A01",
                    "building": "B1",
                    "floor": "F1",
                    "location": "Lobby",
                    "location_to": None,
                    "location_from": None,
                    "hand": None,
                    "width": None,
                    "length": None,
                    "door_thickness": None,
                    "jamb_thickness": None,
                    "door_type": None,
                    "frame_type": None,
                    "interior_exterior": None,
                    "keying": None,
                    "heading_no": None,
                    "single_pair": None,
                    "assignment_multiplier": None,
                }
            ],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": "A01",
                    "items": [{"hardware_category": "HINGE", "product_code": code, "quantity": qty}],
                },
            ],
        },
    )


def test_gate1_refuses_task_when_short_and_creates_no_pr(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=1)  # need 3, only 1 available
    db_session.commit()

    with pytest.raises(InventoryShortfallError) as excinfo:
        _finalize_shop_assembly(db_session, project, code="HG-100", qty=3)

    # The refusal carries the shortfall detail for the creator and the PO notification.
    err = excinfo.value
    assert err.project_id == project.id
    assert len(err.shortfalls) == 1
    assert err.shortfalls[0].short == 2

    db_session.rollback()  # mirror the resolver's rollback of the refused finalize

    # No shop-assembly PR was created.
    prs = db_session.scalars(
        select(PullRequest).where(
            PullRequest.project_id == project.id,
            PullRequest.source == PullRequestSource.SHOP_ASSEMBLY,
        )
    ).all()
    assert prs == []


def test_gate1_allows_task_when_covered(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)  # need 3, exactly covered
    db_session.commit()

    _finalize_shop_assembly(db_session, project, code="HG-100", qty=3)
    db_session.flush()

    pr = db_session.scalar(
        select(PullRequest).where(
            PullRequest.project_id == project.id,
            PullRequest.source == PullRequestSource.SHOP_ASSEMBLY,
        )
    )
    assert pr is not None
    assert pr.status == PullRequestStatus.PENDING


# --- gate 2: warehouse approve_pull_request --------------------------------------------------


def test_gate2_short_leaves_pr_pending_and_notifies_po(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=1)  # need 4, only 1 available
    pr = _make_pending_pr(db_session, project.id, needs=[("HINGE", "HG-100", 4)])
    db_session.flush()

    returned_pr, outcome, notif, shortfalls = warehouse_repository.approve_pull_request(
        db_session, pr.id, "warehouse-user"
    )

    assert outcome == "INSUFFICIENT"
    # PR is left PENDING - blocked, not cancelled.
    assert returned_pr.status == PullRequestStatus.PENDING
    assert returned_pr.cancelled_at is None
    # Exact shortfall returned to the approver.
    assert len(shortfalls) == 1
    assert (shortfalls[0].requested, shortfalls[0].available, shortfalls[0].short) == (4, 1, 3)
    # PO is notified for backfill.
    assert notif is not None
    assert notif.type == NotificationType.INVENTORY_SHORTFALL
    assert len(_po_shortfall_notifs(db_session, project.id)) == 1


def test_gate2_sufficient_approves_and_deducts_fifo(db_session):
    project = _make_project(db_session)
    older = _seed_inventory(db_session, project.id, quantity=2, received_at=datetime(2020, 1, 1))
    newer = _seed_inventory(db_session, project.id, quantity=5, received_at=datetime(2024, 1, 1))
    pr = _make_pending_pr(db_session, project.id, needs=[("HINGE", "HG-100", 3)])
    db_session.flush()

    returned_pr, outcome, notif, shortfalls = warehouse_repository.approve_pull_request(
        db_session, pr.id, "warehouse-user"
    )

    assert outcome == "APPROVED"
    assert returned_pr.status == PullRequestStatus.IN_PROGRESS
    assert notif is None
    assert shortfalls == []
    # FIFO: the older row is drained first (2), then 1 off the newer row.
    assert older.quantity == 0
    assert newer.quantity == 4
    assert _po_shortfall_notifs(db_session, project.id) == []
