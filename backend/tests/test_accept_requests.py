"""Tests for the downstream accept gate (#293 workstream B).

Start-a-Request mints request entities (ShopAssemblyRequest / ShippingOutRequest) PENDING; a signed-in
user accepts them, which mints the existing warehouse PullRequest (PENDING). These exercise the
repository layer directly (the resolvers only add require_user + commit on top).

Since v1 dropped door management the two request types are structurally identical - flat lines
tagged with an opening number - so every test below has a twin on the other side, and where the
behaviour is meant to be the same the two are asserted the same way.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, InventoryShortfallError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    shop_assembly_repository,
    warehouse_admin_repository,
)
from tests.pick_helpers import pick_pull


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=stock.id,
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


def _reservations(session, project_id):
    return session.scalars(select(InventoryReservation).where(InventoryReservation.project_id == project_id)).all()


def _finalize_shop_assembly(session, project, *, code="HG-100", qty=2, opening_number="A01"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number, "building": "B1", "floor": "F2", "location": "Lobby"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {
                    "opening_number": opening_number,
                    "hardware_category": "HINGE",
                    "product_code": code,
                    "quantity": qty,
                },
            ],
        },
    )


def _finalize_shipping(session, project, *, code="HG-100", qty=2, opening_number="A01"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number}],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "opening_number": opening_number,
                            "hardware_category": "HINGE",
                            "product_code": code,
                            "requested_quantity": qty,
                        }
                    ],
                }
            ],
        },
    )


# --- shop-assembly accept / reject -----------------------------------------------------------


def test_accept_shop_assembly_mints_pr_and_links_it_to_the_request(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()

    returned = shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.APPROVED
    assert returned.approved_by == "acceptor"
    assert returned.approved_at is not None

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHOP_ASSEMBLY
    assert pr.status == PullRequestStatus.PENDING
    assert pr.requested_by == "acceptor"
    # The request holds the link now that no opening does.
    assert returned.pull_request_id == pr.id

    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].opening_number == "A01"
    assert pr_items[0].product_code == "HG-100"
    assert pr_items[0].requested_quantity == 2


def test_accept_mints_lines_only_for_what_was_allocated(db_session):
    """The pull asks for the ALLOCATED quantity, and a line with nothing allocated mints no pull line
    at all. That is what keeps the pull equal to the reservation - asking for the owed quantity
    instead would put a product code on the pick sheet that nobody claimed any stock for, so every
    pick of it would confirm short."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=2)
    _seed_inventory(db_session, project.id, category="CLOSER", code="CL-1", quantity=0)
    result = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01", "building": "B1", "floor": "F2", "location": "Lobby"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {
                    "opening_number": "A01",
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "quantity": 4,
                    "allocated_quantity": 2,
                },
                {
                    "opening_number": "A01",
                    "hardware_category": "CLOSER",
                    "product_code": "CL-1",
                    "quantity": 1,
                    "allocated_quantity": 0,
                },
            ],
        },
    )
    sar = result["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1  # the fully-short closer line is not on the sheet
    assert pr_items[0].product_code == "HG-100"
    assert pr_items[0].requested_quantity == 2  # allocated, not the 4 owed

    # The pull asks for exactly what is reserved, which is the invariant the pick relies on.
    reservations = db_session.scalars(
        select(InventoryReservation).where(InventoryReservation.shop_assembly_request_id == sar.id)
    ).all()
    assert [(r.product_code, r.quantity) for r in reservations] == [("HG-100", 2)]


def test_creating_a_shop_assembly_request_blocks_on_shortfall(db_session):
    """#342 moved this gate from accept to creation: a selection that does not fit available
    inventory is refused before anything exists, so there is no request for anyone to accept."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=1)  # need 2

    with pytest.raises(InventoryShortfallError):
        _finalize_shop_assembly(db_session, project, qty=2)

    db_session.rollback()
    assert (
        db_session.scalars(select(PullRequest).where(PullRequest.source == PullRequestSource.SHOP_ASSEMBLY)).all() == []
    )


def test_reject_shop_assembly_request(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()
    assert _reservations(db_session, project.id)  # it was created holding a claim

    returned = shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "not needed")
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.REJECTED
    assert returned.rejected_by == "rejector"
    assert returned.rejection_reason == "not needed"
    assert returned.rejected_at is not None
    # No PR minted on reject.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is None
    # The dead request lets go of the hardware it was holding (#342).
    assert _reservations(db_session, project.id) == []


# --- shop-assembly reopen (#325) -------------------------------------------------------------


def test_reopen_shop_assembly_reverts_to_pending_and_deletes_pr(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    assert pr is not None

    returned = shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.PENDING
    assert returned.approved_by is None
    assert returned.approved_at is None
    assert returned.pull_request_id is None

    # The minted PR and its items are hard-deleted.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is None
    assert db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all() == []

    # The request keeps its claim throughout - reopening does not give the hardware up.
    assert _reservations(db_session, project.id)

    # From PENDING the existing reject flow works (the recovery path the issue wants).
    rejected = shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "mistake")
    db_session.flush()
    assert rejected.status == ShopAssemblyRequestStatus.REJECTED


def test_reopen_shop_assembly_blocked_when_pr_already_worked(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))

    # The warehouse picks the pull (deducts inventory, PR -> IN_PROGRESS). Reopen must now refuse.
    pick_pull(db_session, pr.id, "warehouse")
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)


def test_reopen_shop_assembly_requires_approved(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]  # PENDING, never accepted
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)


def test_reaccepting_a_reopened_request_mints_a_fresh_pull(db_session):
    """The reopen hard-deletes the pull rather than soft-deleting it, because `request_number` is
    unique among live pulls: a second accept re-mints one carrying the same number."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)
    db_session.flush()

    reaccepted = shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    assert pr is not None
    assert reaccepted.pull_request_id == pr.id


# --- shipping-out accept / reject ------------------------------------------------------------


def test_accept_shipping_out_mints_pr_and_copies_items(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]
    req_number = req.request_number
    db_session.flush()

    returned = shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    assert returned.status == ShippingOutRequestStatus.APPROVED
    assert returned.approved_by == "acceptor"
    assert returned.pull_request_id is not None

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHIPPING_OUT
    assert pr.status == PullRequestStatus.PENDING
    assert returned.pull_request_id == pr.id

    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].opening_number == "A01"
    assert pr_items[0].product_code == "HG-100"
    assert pr_items[0].requested_quantity == 2


def test_reject_shipping_out_request(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]
    req_number = req.request_number
    db_session.flush()
    assert _reservations(db_session, project.id)  # the line reserved at creation

    returned = shipping_repository.reject_shipping_out_request(db_session, req.id, "rejector", "  cancelled  ")
    db_session.flush()
    assert _reservations(db_session, project.id) == []

    assert returned.status == ShippingOutRequestStatus.REJECTED
    assert returned.rejected_by == "rejector"
    assert returned.rejection_reason == "cancelled"  # trimmed
    assert returned.pull_request_id is None
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number)) is None


# --- shipping-out reopen (#325) --------------------------------------------------------------


def test_reopen_shipping_out_reverts_to_pending_and_deletes_pr(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]
    req_number = req.request_number
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    assert pr is not None

    returned = shipping_repository.reopen_shipping_out_request(db_session, req.id)
    db_session.flush()

    # Request is back to PENDING, unlinked, with the approve stamps cleared.
    assert returned.status == ShippingOutRequestStatus.PENDING
    assert returned.approved_by is None
    assert returned.approved_at is None
    assert returned.pull_request_id is None

    # The minted PR and its items are hard-deleted.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number)) is None
    assert db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all() == []

    # From PENDING the existing reject flow works (the recovery path the issue wants).
    rejected = shipping_repository.reject_shipping_out_request(db_session, req.id, "rejector", "mistake")
    db_session.flush()
    assert rejected.status == ShippingOutRequestStatus.REJECTED


def test_reopen_shipping_out_blocked_when_pr_already_worked(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req.request_number))

    pick_pull(db_session, pr.id, "warehouse")
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shipping_repository.reopen_shipping_out_request(db_session, req.id)


def test_reopen_shipping_out_requires_approved(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shipping(db_session, project, qty=2)
    req = result["shipping_out_requests"][0]  # PENDING, never accepted
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shipping_repository.reopen_shipping_out_request(db_session, req.id)


# --- reopenable_only filter for the Approved view (#325) --------------------------------------


def test_reopenable_only_excludes_worked_shipping_requests(db_session):
    """The Approved/reopen view passes reopenable_only so it lists only requests still in the reopen
    window (minted PR still PENDING), not every request ever accepted."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    worked = _finalize_shipping(db_session, project, qty=2, opening_number="A01")["shipping_out_requests"][0]
    fresh = _finalize_shipping(db_session, project, qty=2, opening_number="A02")["shipping_out_requests"][0]
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, worked.id, "acceptor")
    shipping_repository.accept_shipping_out_request(db_session, fresh.id, "acceptor")
    db_session.flush()

    # The warehouse starts the pull on one of them (PR -> IN_PROGRESS): it drops out of the window.
    worked_pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == worked.request_number))
    pick_pull(db_session, worked_pr.id, "warehouse")
    db_session.flush()

    reopenable = shipping_repository.get_shipping_out_requests(
        db_session, project.id, ShippingOutRequestStatus.APPROVED, reopenable_only=True
    )
    ids = {r.id for r in reopenable}
    assert fresh.id in ids
    assert worked.id not in ids
    # Without the filter both APPROVED requests still show.
    all_approved = {
        r.id
        for r in shipping_repository.get_shipping_out_requests(
            db_session, project.id, ShippingOutRequestStatus.APPROVED
        )
    }
    assert {worked.id, fresh.id} <= all_approved


def test_reopenable_only_excludes_worked_shop_assembly_requests(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    worked = _finalize_shop_assembly(db_session, project, qty=2, opening_number="A01")["shop_assembly_request"]
    fresh = _finalize_shop_assembly(db_session, project, qty=2, opening_number="A02")["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, worked.id, "acceptor")
    shop_assembly_repository.accept_shop_assembly_request(db_session, fresh.id, "acceptor")
    db_session.flush()

    worked_pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == worked.request_number))
    pick_pull(db_session, worked_pr.id, "warehouse")
    db_session.flush()

    reopenable = shop_assembly_repository.get_shop_assembly_requests(
        db_session, project.id, ShopAssemblyRequestStatus.APPROVED, reopenable_only=True
    )
    ids = {r.id for r in reopenable}
    assert fresh.id in ids
    assert worked.id not in ids


# --- the derived stage the requests page draws as columns --------------------------------------


def test_request_stage_walks_requested_accepted_pulling_done(db_session):
    """The ladder is derived from the request's own status and its pull's - nothing stores it, so
    every rung has to fall out of state that already exists."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    def stage():
        return shop_assembly_repository.get_request_stages(db_session, [sar])[sar.id]

    assert stage() == shop_assembly_repository.STAGE_REQUESTED

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    assert stage() == shop_assembly_repository.STAGE_ACCEPTED

    pick_pull(db_session, sar.pull_request_id, "warehouse")
    db_session.flush()
    assert stage() == shop_assembly_repository.STAGE_PULLING

    from app.repositories import warehouse as warehouse_repository

    warehouse_repository.complete_pull_request(db_session, sar.pull_request_id, "warehouse")
    db_session.flush()
    assert stage() == shop_assembly_repository.STAGE_DONE


def test_a_rejected_request_is_off_the_ladder(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", None)
    db_session.flush()

    assert shop_assembly_repository.get_request_stages(db_session, [sar])[sar.id] == (
        shop_assembly_repository.STAGE_REJECTED
    )


def test_two_requests_for_one_opening_are_both_allowed(db_session):
    """No duplicate-opening guard any more. An opening genuinely may be owed hardware twice, and
    what stops anyone raising the second one by accident is the composer's `claimed` term, not a
    refusal at creation."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)

    first = _finalize_shop_assembly(db_session, project, qty=2, opening_number="A01")["shop_assembly_request"]
    second = _finalize_shop_assembly(db_session, project, qty=2, opening_number="A01")["shop_assembly_request"]
    db_session.flush()

    assert first.id != second.id
    assert first.request_number != second.request_number
    # Both hold their own claim, so the second did not quietly reuse the first's.
    assert sum(r.quantity for r in _reservations(db_session, project.id)) == 4
