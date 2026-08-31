"""Tests for the downstream dispatch gate.

Shipping out is still one accept: Start-a-Request mints a PENDING ShippingOutRequest, a signed-in
user accepts it, and that mints the warehouse PullRequest.

Shop assembly is not (#646). A request is a flag the PM raises over openings - no allocation, no
gate, no reservation - and the Shop Assembly Manager dispatches it in BATCHES, each of which does
what the accept used to. So the two sides are no longer twins, and where they diverge the tests say
which behaviour belongs to which.

These exercise the repository layer directly (the resolvers only add the role gate + commit on top).
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, InventoryShortfallError, ValidationError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
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
from tests.shop_assembly_helpers import batch_pull, batch_request


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
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


# --- shop-assembly creation is a flag, not a claim ---------------------------------------------


def test_creating_a_shop_assembly_request_reserves_nothing_and_gates_on_nothing(db_session):
    """The PM flags openings; the shop may need them long before the hardware exists. So creation
    holds no stock and refuses nothing - there is not even any inventory in this project."""
    project = _make_project(db_session)

    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert _reservations(db_session, project.id) == []
    assert sar.batches == []
    assert [(o.opening_number, o.status) for o in sar.openings] == [("A01", ShopAssemblyOpeningStatus.PENDING)]
    assert [(i.opening_number, i.requested_quantity) for i in sar.items] == [("A01", 2)]
    assert (
        db_session.scalars(select(PullRequest).where(PullRequest.source == PullRequestSource.SHOP_ASSEMBLY)).all() == []
    )


def test_a_shop_assembly_line_must_name_an_opening(db_session):
    """A request IS a list of openings, so a line hanging off none of them could never be batched."""
    project = _make_project(db_session)
    with pytest.raises(ValidationError) as excinfo:
        import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [{"opening_number": "A01"}],
                "hardware_items": [],
                "include_shop_assembly_request": True,
                "shop_assembly_items": [
                    {"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 2},
                ],
            },
        )
    assert excinfo.value.field == "opening_number"


# --- batching (what the accept became) ---------------------------------------------------------


def test_batching_mints_a_pull_reserves_its_lines_and_consumes_its_openings(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    batch = batch_request(db_session, sar.id, created_by="manager")
    db_session.flush()

    assert batch.sequence == 1
    assert batch.batch_number == f"{sar.request_number}-B1"
    assert batch.status == ShopAssemblyBatchStatus.ACTIVE
    assert [(i.opening_number, i.product_code, i.allocated_quantity) for i in batch.items] == [("A01", "HG-100", 2)]

    pr = batch_pull(db_session, batch)
    assert pr is not None
    assert pr.request_number == batch.batch_number
    assert pr.source == PullRequestSource.SHOP_ASSEMBLY
    assert pr.status == PullRequestStatus.PENDING
    assert pr.requested_by == "manager"

    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert [(i.opening_number, i.product_code, i.requested_quantity) for i in pr_items] == [("A01", "HG-100", 2)]

    # The pull asks for exactly what is reserved, which is the invariant the pick relies on, and the
    # claim hangs off the BATCH rather than the request.
    reservations = db_session.scalars(
        select(InventoryReservation).where(InventoryReservation.shop_assembly_batch_id == batch.id)
    ).all()
    assert [(r.product_code, r.quantity) for r in reservations] == [("HG-100", 2)]

    db_session.refresh(sar, attribute_names=["openings", "batches"])
    assert [(o.opening_number, o.status) for o in sar.openings] == [("A01", ShopAssemblyOpeningStatus.BATCHED)]
    # Nothing left pending, so the request closed itself out.
    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    assert sar.approved_by == "manager"


def test_a_partial_batch_forfeits_the_remainder_and_consumes_the_opening(db_session):
    """Partials are allowed and the batch IS the decision for that opening: the two units it could
    not take are gone, not left as a backlog row nobody works."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=2)
    sar = _finalize_shop_assembly(db_session, project, qty=4)["shop_assembly_request"]
    db_session.flush()

    batch = batch_request(db_session, sar.id, quantities={("A01", "HINGE", "HG-100"): 2})
    db_session.flush()

    pr = batch_pull(db_session, batch)
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert [i.requested_quantity for i in pr_items] == [2]

    db_session.refresh(sar, attribute_names=["openings"])
    assert sar.openings[0].status == ShopAssemblyOpeningStatus.BATCHED
    # The line still says what it was owed - the request is the record of the demand, not of the
    # dispatch - and nothing re-offers the missing two.
    assert [i.requested_quantity for i in sar.items] == [4]


def test_batching_leaves_unbatched_openings_pending_for_the_next_one(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": n, "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 2}
                for n in ("A01", "A02")
            ],
        },
    )["shop_assembly_request"]
    db_session.flush()

    first = batch_request(db_session, sar.id, openings=["A01"])
    db_session.flush()
    db_session.refresh(sar, attribute_names=["openings", "batches"])

    assert sar.status == ShopAssemblyRequestStatus.PENDING  # A02 is still waiting
    assert {o.opening_number: o.status for o in sar.openings} == {
        "A01": ShopAssemblyOpeningStatus.BATCHED,
        "A02": ShopAssemblyOpeningStatus.PENDING,
    }

    second = batch_request(db_session, sar.id)
    db_session.flush()
    db_session.refresh(sar, attribute_names=["openings", "batches"])

    assert second.sequence == 2
    assert second.batch_number == f"{sar.request_number}-B2"
    assert first.batch_number != second.batch_number
    assert sar.status == ShopAssemblyRequestStatus.APPROVED


def test_a_batch_is_gated_on_available_inventory(db_session):
    """The gate the creation path lost. It applies to exactly this batch's allocations, at the moment
    the manager commits to them."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=1)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    with pytest.raises(InventoryShortfallError):
        batch_request(db_session, sar.id)

    db_session.rollback()
    assert (
        db_session.scalars(select(PullRequest).where(PullRequest.source == PullRequestSource.SHOP_ASSEMBLY)).all() == []
    )


def test_a_batch_cannot_allocate_more_than_the_opening_is_owed(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        batch_request(db_session, sar.id, quantities={("A01", "HINGE", "HG-100"): 3})
    assert excinfo.value.field == "allocated_quantity"


def test_an_opening_with_nothing_allocatable_simply_stays_pending(db_session):
    """The #645 case. An opening whose hardware has not arrived is not dispatched as an empty cart -
    it has no lines to put on a batch, so it stays on the board until there is stock."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=4)
    _seed_inventory(db_session, project.id, category="CLOSER", code="CL-1", quantity=0)
    sar = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 4},
                {"opening_number": "A02", "hardware_category": "CLOSER", "product_code": "CL-1", "quantity": 1},
            ],
        },
    )["shop_assembly_request"]
    db_session.flush()

    batch_request(db_session, sar.id, openings=["A01"])
    db_session.flush()
    db_session.refresh(sar, attribute_names=["openings"])

    assert {o.opening_number: o.status for o in sar.openings} == {
        "A01": ShopAssemblyOpeningStatus.BATCHED,
        "A02": ShopAssemblyOpeningStatus.PENDING,
    }
    assert sar.status == ShopAssemblyRequestStatus.PENDING


def test_batching_an_opening_that_is_no_longer_pending_is_refused(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()
    lines = [{"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "allocated_quantity": 1}]
    shop_assembly_repository.create_shop_assembly_batch(db_session, sar.id, lines, created_by="manager")
    db_session.flush()

    # The request closed out, so it is not even batchable any more.
    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.create_shop_assembly_batch(db_session, sar.id, lines, created_by="manager")


# --- dismissal and whole-request rejection -----------------------------------------------------


def test_dismissing_the_remainder_closes_the_request(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": n, "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 2}
                for n in ("A01", "A02")
            ],
        },
    )["shop_assembly_request"]
    db_session.flush()
    batch_request(db_session, sar.id, openings=["A01"])
    db_session.flush()

    shop_assembly_repository.dismiss_shop_assembly_openings(
        db_session, sar.id, None, dismissed_by="manager", reason="  never arrived  "
    )
    db_session.flush()
    db_session.refresh(sar, attribute_names=["openings"])

    dismissed = next(o for o in sar.openings if o.opening_number == "A02")
    assert dismissed.status == ShopAssemblyOpeningStatus.DISMISSED
    assert dismissed.dismissed_by == "manager"
    assert dismissed.dismissal_reason == "never arrived"  # trimmed
    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    # Dismissing releases nothing, because a pending opening never held anything.
    assert sum(r.quantity for r in _reservations(db_session, project.id)) == 2


def test_rejecting_an_unbatched_request_releases_nothing_and_mints_nothing(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()
    assert _reservations(db_session, project.id) == []  # it never held a claim

    returned = shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "not needed")
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.REJECTED
    assert returned.rejected_by == "rejector"
    assert returned.rejection_reason == "not needed"
    assert returned.rejected_at is not None
    assert _reservations(db_session, project.id) == []


def test_a_batched_request_cannot_be_rejected_whole(db_session):
    """Part of it has already happened - hardware is reserved and a pull is on the floor - so the
    honest ways out are cancelling that pull and dismissing what is left."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": n, "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 2}
                for n in ("A01", "A02")
            ],
        },
    )["shop_assembly_request"]
    db_session.flush()
    batch_request(db_session, sar.id, openings=["A01"])
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError, match="already been batched"):
        shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", None)


# --- discarding a batch (the #325 reopen, at batch granularity) -------------------------------


def test_discarding_a_batch_deletes_its_pull_releases_its_claim_and_reopens_its_openings(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()
    batch = batch_request(db_session, sar.id)
    db_session.flush()
    pr_id = batch.pull_request_id
    batch_id = batch.id
    assert _reservations(db_session, project.id)

    returned = shop_assembly_repository.discard_shop_assembly_batch(db_session, batch_id)
    db_session.flush()

    assert returned.status == ShopAssemblyRequestStatus.PENDING
    assert returned.approved_by is None
    assert returned.batches == []
    assert [o.status for o in returned.openings] == [ShopAssemblyOpeningStatus.PENDING]
    assert db_session.scalar(select(PullRequest).where(PullRequest.id == pr_id)) is None
    assert db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr_id)).all() == []
    assert _reservations(db_session, project.id) == []


def test_discard_is_blocked_once_the_warehouse_has_started_the_pull(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()
    batch = batch_request(db_session, sar.id)
    db_session.flush()

    pick_pull(db_session, batch.pull_request_id, "warehouse")
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.discard_shop_assembly_batch(db_session, batch.id)


def test_re_batching_after_a_discard_takes_the_next_number(db_session):
    """The discard hard-deletes the batch and its pull, and the sequence still moves on: a cancelled
    pull elsewhere may be keeping the old number for the record."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    first = batch_request(db_session, sar.id)
    db_session.flush()
    first_number = first.batch_number
    shop_assembly_repository.discard_shop_assembly_batch(db_session, first.id)
    db_session.flush()

    again = batch_request(db_session, sar.id)
    db_session.flush()

    # The discard removed batch 1 entirely, so the max sequence is back to 0 and this is B1 again -
    # legal precisely because nothing carrying that number survives.
    assert again.batch_number == first_number
    assert batch_pull(db_session, again) is not None


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

    worked_batch = batch_request(db_session, worked.id)
    batch_request(db_session, fresh.id)
    db_session.flush()

    pick_pull(db_session, worked_batch.pull_request_id, "warehouse")
    db_session.flush()

    reopenable = shop_assembly_repository.get_shop_assembly_requests(
        db_session, project.id, ShopAssemblyRequestStatus.APPROVED, reopenable_only=True
    )
    ids = {r.id for r in reopenable}
    assert fresh.id in ids
    assert worked.id not in ids


# --- the derived stage the requests page draws as columns --------------------------------------


def test_request_stage_walks_requested_accepted_pulling_done(db_session):
    """The ladder is derived from the request's own status and its batches' pulls - nothing stores
    it, so every rung has to fall out of state that already exists."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    def stage():
        fresh = shop_assembly_repository.get_shop_assembly_request(db_session, sar.id)
        return shop_assembly_repository.get_request_stages(db_session, [fresh])[sar.id]

    assert stage() == shop_assembly_repository.STAGE_REQUESTED

    batch = batch_request(db_session, sar.id)
    db_session.flush()
    assert stage() == shop_assembly_repository.STAGE_ACCEPTED

    pick_pull(db_session, batch.pull_request_id, "warehouse")
    db_session.flush()
    assert stage() == shop_assembly_repository.STAGE_PULLING

    from app.repositories import warehouse as warehouse_repository

    warehouse_repository.complete_pull_request(db_session, batch.pull_request_id, "warehouse")
    db_session.flush()
    assert stage() == shop_assembly_repository.STAGE_DONE


def test_a_part_batched_request_still_reads_as_requested(db_session):
    """The amber "somebody has to act on this" rung is about the openings still waiting, not about
    what the warehouse is doing with an earlier batch."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": n, "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 2}
                for n in ("A01", "A02")
            ],
        },
    )["shop_assembly_request"]
    db_session.flush()
    batch = batch_request(db_session, sar.id, openings=["A01"])
    db_session.flush()
    pick_pull(db_session, batch.pull_request_id, "warehouse")
    db_session.flush()

    fresh = shop_assembly_repository.get_shop_assembly_request(db_session, sar.id)
    assert shop_assembly_repository.get_request_stages(db_session, [fresh])[sar.id] == (
        shop_assembly_repository.STAGE_REQUESTED
    )


def test_a_request_finished_entirely_by_dismissal_is_done(db_session):
    project = _make_project(db_session)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.dismiss_shop_assembly_openings(
        db_session, sar.id, None, dismissed_by="manager", reason=None
    )
    db_session.flush()

    fresh = shop_assembly_repository.get_shop_assembly_request(db_session, sar.id)
    assert fresh.status == ShopAssemblyRequestStatus.APPROVED
    assert shop_assembly_repository.get_request_stages(db_session, [fresh])[sar.id] == (
        shop_assembly_repository.STAGE_DONE
    )


def test_a_rejected_request_is_off_the_ladder(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_shop_assembly(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", None)
    db_session.flush()

    fresh = shop_assembly_repository.get_shop_assembly_request(db_session, sar.id)
    assert shop_assembly_repository.get_request_stages(db_session, [fresh])[sar.id] == (
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

    batch_request(db_session, first.id)
    batch_request(db_session, second.id)
    db_session.flush()
    # Each batch holds its own claim, so the second did not quietly reuse the first's.
    assert sum(r.quantity for r in _reservations(db_session, project.id)) == 4
