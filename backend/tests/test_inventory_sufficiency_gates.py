"""Tests for the hard inventory-sufficiency gates and the shared helper (#224 / #293 / #342).

Gate 1 moved twice. It started at import "Start a Request", moved to accept in #293, and moved back to
creation in #342 - this time as a *reservation*: creating a request gates on
`on-hand - deficient - other requests' reservations` and writes its own claim. Accept is now a pure
human gate that re-checks nothing, because the hardware is already this request's.

Gate 2 moved with it in #367. It used to be an approve-time refusal that left the pull PENDING; the
deduction now happens at `confirm_pick`, so a pull that cannot be filled is *picked short* rather
than blocked - what is on the shelf comes off, the pull stays In Progress and un-picked, and the
remainder is entered later. Both gates still notify the PO with an INVENTORY_SHORTFALL signal
carrying the shortfall detail, which is what the backfill loop hangs off.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InventoryShortfallError
from app.models.enums import (
    NotificationType,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.notification import Notification
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyRequest
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository
from tests.pick_helpers import pick_pull


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
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
        row="1",
        bay="1",
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


# --- gate 1: creating a shop-assembly request (#342) -----------------------------------------


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
            "shop_assembly_items": [
                {"opening_number": "A01", "hardware_category": "HINGE", "product_code": code, "quantity": qty},
            ],
        },
    )


def test_gate1_creation_refuses_when_short_and_creates_nothing(db_session):
    """#342: the gate is at creation. A selection that does not fit available inventory is refused
    whole, naming the shorted combo, and nothing at all is written - the creator refines the
    selection, which is the only point in the flow where that is still cheap."""
    project = _make_project(db_session)
    project_id = project.id
    _seed_inventory(db_session, project_id, quantity=1)  # need 3, only 1 available
    db_session.commit()

    with pytest.raises(InventoryShortfallError) as excinfo:
        _finalize_shop_assembly(db_session, project, code="HG-100", qty=3)

    err = excinfo.value
    assert err.project_id == project_id
    assert len(err.shortfalls) == 1
    assert (err.shortfalls[0].requested, err.shortfalls[0].available, err.shortfalls[0].short) == (3, 1, 2)

    db_session.rollback()
    assert (
        db_session.scalars(select(ShopAssemblyRequest).where(ShopAssemblyRequest.project_id == project_id)).all() == []
    )
    assert (
        db_session.scalars(select(InventoryReservation).where(InventoryReservation.project_id == project_id)).all()
        == []
    )


def test_gate1_creation_reserves_what_it_takes(db_session):
    """A covered creation writes the claim, and the claim is what later readers see as unavailable."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, code="HG-100", qty=3)
    db_session.flush()

    reservations = db_session.scalars(
        select(InventoryReservation).where(InventoryReservation.project_id == project.id)
    ).all()
    assert len(reservations) == 1
    assert reservations[0].quantity == 3
    assert reservations[0].source == ReservationSource.SHOP_ASSEMBLY_REQUEST
    assert reservations[0].shop_assembly_request_id == result["shop_assembly_request"].id

    # 5 on hand, 3 claimed -> 2 left for anyone else.
    check = warehouse_repository.check_inventory_sufficiency(
        db_session, project.id, [("HINGE", "HG-100", 3)], reservation_aware=True
    )
    assert not check.sufficient
    assert (check.shortfalls[0].available, check.shortfalls[0].reserved) == (2, 3)


def test_gate1_accept_no_longer_rechecks_inventory(db_session):
    """Accept is a pure human gate (#342). Even if stock is written off after creation, the accept
    still mints the PR - the request holds a reservation, and the place that decision was made was
    creation. (The warehouse approve is what would then surface the discrepancy.)"""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=3)
    result = _finalize_shop_assembly(db_session, project, code="HG-100", qty=3)
    sar_id = result["shop_assembly_request"].id
    db_session.flush()

    il.quantity = 0  # an admin write-off under a live claim
    db_session.flush()

    sar = shop_assembly_repository.accept_shop_assembly_request(db_session, sar_id, "acceptor")
    db_session.flush()

    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is not None
    # Accepting neither spends nor releases the claim.
    assert (
        len(db_session.scalars(select(InventoryReservation).where(InventoryReservation.project_id == project.id)).all())
        == 1
    )


def test_gate1_accept_mints_pr_when_covered(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)  # need 3, exactly covered
    result = _finalize_shop_assembly(db_session, project, code="HG-100", qty=3)
    db_session.flush()

    sar = shop_assembly_repository.accept_shop_assembly_request(
        db_session, result["shop_assembly_request"].id, "acceptor"
    )
    db_session.flush()

    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    assert sar.approved_by == "acceptor"

    pr = db_session.scalar(
        select(PullRequest).where(
            PullRequest.project_id == project.id,
            PullRequest.source == PullRequestSource.SHOP_ASSEMBLY,
        )
    )
    assert pr is not None
    assert pr.status == PullRequestStatus.PENDING
    assert pr.request_number == sar.request_number


# --- gate 2: the warehouse pick (#367) ---------------------------------------------------------


def test_gate2_short_pick_keeps_the_pull_open_and_notifies_po(db_session):
    """A pull that cannot be filled is no longer refused at approve - it is picked short.

    The difference is real, not cosmetic. The old behaviour put back the one hinge that *was* there
    and left the pull PENDING, so the warehouse had nothing to show for the trip; now the unit comes
    off the shelf, the pull stays In Progress holding it, and the remainder is entered when the
    backfill lands."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=1)  # need 4, only 1 available
    pr = _make_pending_pr(db_session, project.id, needs=[("HINGE", "HG-100", 4)])
    db_session.flush()

    result = pick_pull(db_session, pr.id, "warehouse-user")

    assert result.outcome == "SHORT"
    # In Progress and un-picked: resumable, not blocked.
    assert result.pull_request.status == PullRequestStatus.IN_PROGRESS
    assert result.pull_request.picked_at is None
    assert result.pull_request.cancelled_at is None
    # What was there did come off the shelf.
    assert row.quantity == 0
    assert result.applied_quantity == 1
    # Exact shortfall returned to the picker.
    assert len(result.shortfalls) == 1
    assert (result.shortfalls[0].requested, result.shortfalls[0].short) == (4, 3)
    # PO is notified for backfill.
    assert result.notification is not None
    assert result.notification.type == NotificationType.INVENTORY_SHORTFALL
    assert len(_po_shortfall_notifs(db_session, project.id)) == 1


def test_gate2_full_pick_stamps_picked_and_deducts_the_rows_dictated(db_session):
    project = _make_project(db_session)
    older = _seed_inventory(db_session, project.id, quantity=2, received_at=datetime(2020, 1, 1))
    newer = _seed_inventory(db_session, project.id, quantity=5, received_at=datetime(2024, 1, 1))
    pr = _make_pending_pr(db_session, project.id, needs=[("HINGE", "HG-100", 3)])
    db_session.flush()

    result = pick_pull(db_session, pr.id, "warehouse-user")

    assert result.outcome == "PICKED"
    assert result.pull_request.status == PullRequestStatus.IN_PROGRESS
    assert result.pull_request.picked_at is not None
    assert result.pull_request.picked_by == "warehouse-user"
    assert result.notification is None
    assert result.shortfalls == []
    # The helper dictates oldest-first, so this is the same split the old FIFO produced - the point
    # being that the split is now something a caller chose, not something the system decided.
    assert older.quantity == 0
    assert newer.quantity == 4
    assert _po_shortfall_notifs(db_session, project.id) == []
