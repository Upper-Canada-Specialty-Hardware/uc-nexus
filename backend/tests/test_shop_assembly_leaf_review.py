"""Per-leaf shop-assembly review (#495).

Review moved from the request to the door leaf. A request covering several doors where one is short
used to be a single all-or-nothing decision, so the reviewer either held the ready doors hostage to
the short one or accepted work the shop could not do.

Two things carry the weight here and are what these tests pin:

- **A per-leaf turn-down frees exactly that leaf's hardware.** Reservations are keyed
  (source, request_id) with no opening column, so the whole-request `release_reservations` would
  hand back the siblings' claim too. `release_partial_reservations` decrements per combo instead.
- **Acceptances arrive one at a time, so a pull is minted or appended to.** A leaf joins the
  request's pull while that pull is still PENDING; once it is IN_PROGRESS its sheet is printed and
  in a picker's hands, so a later acceptance starts a second pull rather than growing a document
  somebody is already working from.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError
from app.models.enums import (
    OpeningReviewStatus,
    PullRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Leaf review")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity):
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
    session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project_id,
            stock_item_id=si.id,
            warehouse_id=warehouse_id,
            hardware_category=category,
            product_code=code,
            quantity=quantity,
            deficient_quantity=0,
            aisle="A",
            row="1",
            bay="1",
            received_at=datetime.utcnow(),
        )
    )
    session.flush()


def _two_leaf_request(session, project, *, qty=2):
    """One request covering two door leaves, each owed `qty` of the same product."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [
                {"opening_number": "A01", "building": "B1", "floor": "F2", "location": "Lobby"},
                {"opening_number": "A02", "building": "B1", "floor": "F2", "location": "Corridor"},
            ],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": "A01",
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": qty}],
                },
                {
                    "opening_number": "A02",
                    "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": qty}],
                },
            ],
        },
    )["shop_assembly_request"]


def _openings(session, sar_id):
    return list(
        session.scalars(
            select(ShopAssemblyOpening)
            .where(ShopAssemblyOpening.shop_assembly_request_id == sar_id)
            .order_by(ShopAssemblyOpening.opening_number)
        ).all()
    )


def _reserved_units(session, project_id) -> int:
    return sum(
        r.quantity
        for r in session.scalars(
            select(InventoryReservation).where(InventoryReservation.project_id == project_id)
        ).all()
    )


def test_accepting_one_leaf_leaves_its_siblings_pending(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)
    first, second = _openings(db_session, sar.id)

    shop_assembly_repository.accept_shop_assembly_opening(db_session, first.id, reviewed_by="reviewer")
    db_session.flush()

    assert first.review_status == OpeningReviewStatus.ACCEPTED
    assert first.reviewed_by == "reviewer"
    assert second.review_status == OpeningReviewStatus.PENDING
    # The request is a rollup now: still Pending because a leaf on it still is.
    db_session.refresh(sar)
    assert sar.status == ShopAssemblyRequestStatus.PENDING

    # Only the accepted leaf is on a pull.
    assert first.pull_request_id is not None
    assert second.pull_request_id is None


def test_the_second_accepted_leaf_joins_the_same_open_pull(db_session):
    """One pick sheet per request, not per door - as long as the sheet has not been printed."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)
    first, second = _openings(db_session, sar.id)

    shop_assembly_repository.accept_shop_assembly_opening(db_session, first.id, reviewed_by="reviewer")
    shop_assembly_repository.accept_shop_assembly_opening(db_session, second.id, reviewed_by="reviewer")
    db_session.flush()

    assert first.pull_request_id == second.pull_request_id
    pull = db_session.get(PullRequest, first.pull_request_id)
    # The first pull carries the request's own number, so the sheet reads as what the shop raised.
    assert pull.request_number == sar.request_number

    items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pull.id)).all()
    assert sorted(i.opening_number for i in items) == ["A01", "A02"]

    db_session.refresh(sar)
    assert sar.status == ShopAssemblyRequestStatus.APPROVED


def test_a_leaf_accepted_after_picking_started_gets_its_own_pull(db_session):
    """A printed sheet cannot grow a line. The picker would be working from a document that no
    longer matches what the system thinks they were asked for, so the late leaf gets a second one."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)
    first, second = _openings(db_session, sar.id)

    shop_assembly_repository.accept_shop_assembly_opening(db_session, first.id, reviewed_by="reviewer")
    db_session.flush()
    pull_one = db_session.get(PullRequest, first.pull_request_id)
    pull_one.status = PullRequestStatus.IN_PROGRESS
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_opening(db_session, second.id, reviewed_by="reviewer")
    db_session.flush()

    assert second.pull_request_id != first.pull_request_id
    pull_two = db_session.get(PullRequest, second.pull_request_id)
    assert pull_two.status == PullRequestStatus.PENDING
    # A second live pull cannot reuse the number - it takes the next off the project's sequence.
    assert pull_two.request_number != pull_one.request_number
    assert pull_two.request_number.startswith(project.project_id)


def test_rejecting_one_leaf_frees_only_its_own_hardware(db_session):
    """Reservations are keyed (source, request_id) with no opening column, so the whole-request
    release would hand back the sibling's claim too."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project, qty=2)
    first, second = _openings(db_session, sar.id)
    assert _reserved_units(db_session, project.id) == 4

    shop_assembly_repository.reject_shop_assembly_opening(
        db_session, first.id, reviewed_by="reviewer", reason="Wrong handing"
    )
    db_session.flush()

    assert first.review_status == OpeningReviewStatus.REJECTED
    assert first.review_reason == "Wrong handing"
    # Exactly the rejected leaf's two units came back; the sibling still holds its claim.
    assert _reserved_units(db_session, project.id) == 2
    assert second.review_status == OpeningReviewStatus.PENDING


def test_deferring_frees_the_hardware_and_shows_in_the_set_aside_queue(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project, qty=2)
    first, _second = _openings(db_session, sar.id)

    shop_assembly_repository.defer_shop_assembly_opening(
        db_session, first.id, reviewed_by="reviewer", reason="Site not ready"
    )
    db_session.flush()

    assert first.review_status == OpeningReviewStatus.DEFERRED
    assert _reserved_units(db_session, project.id) == 2

    deferred = shop_assembly_repository.get_deferred_review_openings(db_session, project.id)
    assert [r["opening"].opening_number for r in deferred] == ["A01"]
    # And it is out of the queue somebody is working.
    pending = shop_assembly_repository.get_pending_review_openings(db_session, project.id)
    assert [r["opening"].opening_number for r in pending] == ["A02"]


def test_a_leaf_can_only_be_reviewed_once(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)
    first, _second = _openings(db_session, sar.id)

    shop_assembly_repository.accept_shop_assembly_opening(db_session, first.id, reviewed_by="reviewer")
    db_session.flush()

    for again in (
        shop_assembly_repository.accept_shop_assembly_opening,
        shop_assembly_repository.reject_shop_assembly_opening,
        shop_assembly_repository.defer_shop_assembly_opening,
    ):
        with pytest.raises(InvalidStateTransitionError):
            again(db_session, first.id, reviewed_by="reviewer")
        db_session.rollback()


def test_a_request_whose_every_leaf_was_turned_down_reads_as_rejected(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)
    first, second = _openings(db_session, sar.id)

    shop_assembly_repository.reject_shop_assembly_opening(db_session, first.id, reviewed_by="reviewer")
    shop_assembly_repository.reject_shop_assembly_opening(db_session, second.id, reviewed_by="reviewer")
    db_session.flush()
    db_session.refresh(sar)

    assert sar.status == ShopAssemblyRequestStatus.REJECTED
    # Nothing was accepted, so nothing was asked of the warehouse.
    assert _reserved_units(db_session, project.id) == 0
    assert db_session.scalar(select(PullRequest).where(PullRequest.project_id == project.id)) is None


def test_accepting_the_whole_request_still_works_and_mints_one_pull(db_session):
    """The request-level accept survives as a bulk decision over every leaf still awaiting one, so
    a reviewer who has nothing to single out is not made to click through each door."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)

    returned = shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.APPROVED
    assert returned.approved_by == "acceptor"
    openings = _openings(db_session, sar.id)
    assert {o.review_status for o in openings} == {OpeningReviewStatus.ACCEPTED}
    assert len({o.pull_request_id for o in openings}) == 1


def test_the_request_accept_refuses_once_every_leaf_is_decided(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _two_leaf_request(db_session, project)
    first, second = _openings(db_session, sar.id)

    shop_assembly_repository.accept_shop_assembly_opening(db_session, first.id, reviewed_by="reviewer")
    shop_assembly_repository.accept_shop_assembly_opening(db_session, second.id, reviewed_by="reviewer")
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
