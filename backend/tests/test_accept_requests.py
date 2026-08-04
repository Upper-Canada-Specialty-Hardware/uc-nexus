"""Tests for the downstream accept gate (#293 workstream B).

Start-a-Request mints request entities (ShopAssemblyRequest / ShippingOutRequest) PENDING; a signed-in
user accepts them, which mints the existing warehouse PullRequest (PENDING). These exercise the
repository layer directly (the resolvers only add require_user + commit on top).
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, InventoryShortfallError, ValidationError
from app.models.enums import (
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.opening_item import OpeningItem, OpeningItemHardware
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shop_assembly import ShopAssemblyOpening
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    shop_assembly_repository,
    warehouse_admin_repository,
)
from app.repositories import warehouse as warehouse_repository
from tests.pick_helpers import pick_pull


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
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
    il = InventoryLocation(
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
    session.add(il)
    session.flush()
    return il


def _reservations(session, project_id):
    """Every live reservation in a project (#342) - the claim requests hold on loose stock."""
    return list(
        session.scalars(select(InventoryReservation).where(InventoryReservation.project_id == project_id)).all()
    )


def _finalize_shop_assembly(session, project, *, code="HG-100", qty=2, opening_number="A01"):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number, "building": "B1", "floor": "F2", "location": "Lobby"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": opening_number,
                    "items": [{"hardware_category": "HINGE", "product_code": code, "quantity": qty}],
                },
            ],
        },
    )


def _make_assembled_leaf(session, project, opening, *, leaf, code="HG-100", category="HINGE"):
    """An assembled door leaf sitting in inventory: what shop assembly leaves behind (#311)."""
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number=opening.opening_number,
        leaf=leaf,
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=OpeningItemState.IN_INVENTORY,
    )
    session.add(oi)
    session.flush()
    session.add(
        OpeningItemHardware(
            id=uuid.uuid4(),
            opening_item_id=oi.id,
            product_code=code,
            hardware_category=category,
            quantity=1,
        )
    )
    session.flush()
    return oi


def _finalize_shipping_leaves(session, project, opening_items, *, send_leaf=True):
    """Finalize a shipping-out request made of OPENING_ITEM lines, one per assembled leaf (#335)."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "item_type": "OPENING_ITEM",
                            "opening_number": oi.opening_number,
                            "opening_item_id": str(oi.id),
                            "leaf": oi.leaf if send_leaf else None,
                            "requested_quantity": 1,
                        }
                        for oi in opening_items
                    ],
                }
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
                            "item_type": "LOOSE",
                            "opening_number": opening_number,
                            "opening_item_id": None,
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


def test_accept_shop_assembly_mints_pr_and_repoints_openings(db_session):
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

    # A SHOP_ASSEMBLY PullRequest is minted PENDING with the SAR's request number.
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHOP_ASSEMBLY
    assert pr.status == PullRequestStatus.PENDING
    assert pr.requested_by == "acceptor"

    # The SAR's openings are repointed at the new PR.
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id))
    assert sao.pull_request_id == pr.id

    # One LOOSE PR item per opening item, so the unchanged warehouse approve deducts FIFO.
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].item_type == PullRequestItemType.LOOSE
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
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": "A01",
                    "leaf": 1,
                    "items": [
                        {
                            "hardware_category": "HINGE",
                            "product_code": "HG-100",
                            "quantity": 4,
                            "allocated_quantity": 2,
                        },
                        {
                            "hardware_category": "CLOSER",
                            "product_code": "CL-1",
                            "quantity": 1,
                            "allocated_quantity": 0,
                        },
                    ],
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

    # The pull asks for exactly what is reserved, which is the invariant approval relies on.
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

    # Request is back to PENDING with the approve stamps cleared.
    assert returned.status == ShopAssemblyRequestStatus.PENDING
    assert returned.approved_by is None
    assert returned.approved_at is None

    # The minted PR and its items are hard-deleted, and the openings no longer point at it.
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is None
    assert db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all() == []
    openings = db_session.scalars(
        select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id)
    ).all()
    assert openings
    assert all(o.pull_request_id is None for o in openings)

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

    # Warehouse approves the pull (deducts inventory, PR -> IN_PROGRESS). Reopen must now refuse.
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


def test_reopen_shop_assembly_discards_pr_when_openings_do_not_reference_it(db_session):
    """Regression: reopen must find the minted PR by request_number, not by the openings'
    pull_request_id. accept mints the PR unconditionally, so an openings-derived lookup would leave it
    orphaned (and the next accept would collide on the unique request_number)."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    result = _finalize_shop_assembly(db_session, project, qty=2)
    sar = result["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    # Simulate the orphan case: the openings no longer point at the minted PR, so a lookup that derived
    # the PR from them would find nothing and skip the delete.
    for opening in db_session.scalars(
        select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id)
    ).all():
        opening.pull_request_id = None
    db_session.flush()

    shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)
    db_session.flush()

    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number)) is None


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

    # A SHIPPING_OUT PR is minted PENDING with the request's number and copied items.
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number))
    assert pr is not None
    assert pr.source == PullRequestSource.SHIPPING_OUT
    assert pr.status == PullRequestStatus.PENDING
    assert returned.pull_request_id == pr.id

    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 1
    assert pr_items[0].item_type == PullRequestItemType.LOOSE
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
    assert _reservations(db_session, project.id)  # the LOOSE line reserved at creation

    returned = shipping_repository.reject_shipping_out_request(db_session, req.id, "rejector", "  cancelled  ")
    db_session.flush()
    assert _reservations(db_session, project.id) == []

    assert returned.status == ShippingOutRequestStatus.REJECTED
    assert returned.rejected_by == "rejector"
    assert returned.rejection_reason == "cancelled"  # trimmed
    assert returned.pull_request_id is None
    assert db_session.scalar(select(PullRequest).where(PullRequest.request_number == req_number)) is None


# --- #335 assembled door leaves ship as OPENING_ITEM lines -----------------------------------


def _seed_pair(session, *, opening_number="0019-EX"):
    """A project whose opening_number is a pair with both leaves assembled and in inventory."""
    project = _make_project(session)
    session.flush()
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number, "leaf_count": 2}],
            "hardware_items": [],
        },
    )
    session.flush()
    opening = session.scalar(
        select(Opening).where(Opening.project_id == project.id, Opening.opening_number == opening_number)
    )
    leaf1 = _make_assembled_leaf(session, project, opening, leaf=1)
    leaf2 = _make_assembled_leaf(session, project, opening, leaf=2)
    return project, leaf1, leaf2


def test_accept_shipping_out_carries_leaf_onto_opening_item_pull_lines(db_session):
    """A pair yields two distinguishable pull lines, each naming its own assembled leaf."""
    project, leaf1, leaf2 = _seed_pair(db_session)
    result = _finalize_shipping_leaves(db_session, project, [leaf1, leaf2])
    req = result["shipping_out_requests"][0]
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req.request_number))
    assert pr.source == PullRequestSource.SHIPPING_OUT
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert len(pr_items) == 2
    assert {i.item_type for i in pr_items} == {PullRequestItemType.OPENING_ITEM}
    # The OpeningItem id survives the hop: without it approve skips the line and complete never
    # flips a leaf to SHIP_READY, which is the #335 dead end.
    assert {i.opening_item_id for i in pr_items} == {leaf1.id, leaf2.id}
    assert sorted(i.leaf for i in pr_items) == [1, 2]


def test_accept_shipping_out_falls_back_to_opening_item_leaf(db_session):
    """Requests written before shipping_out_request_items.leaf existed still label their leaves.

    The legacy state is written directly rather than composed, because since #451 no creation path
    can produce it any more: an OPENING_ITEM line takes its leaf off the assembled row when the
    composer does not name one. What is pinned here is the accept's fallback over rows that are
    ALREADY null in the database, which is exactly the population that predates the column.
    """
    project, leaf1, leaf2 = _seed_pair(db_session)
    result = _finalize_shipping_leaves(db_session, project, [leaf1, leaf2], send_leaf=False)
    req = result["shipping_out_requests"][0]
    db_session.flush()
    for item in req.items:
        item.leaf = None
    db_session.flush()
    assert {i.leaf for i in req.items} == {None}

    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req.request_number))
    pr_items = db_session.scalars(select(PullRequestItem).where(PullRequestItem.pull_request_id == pr.id)).all()
    assert sorted(i.leaf for i in pr_items) == [1, 2]


def test_opening_item_shipping_line_approves_and_pulls_leaves_to_ship_ready(db_session):
    """The whole #335 chain: an assembled-leaf request approves with no loose stock and pulls."""
    project, leaf1, leaf2 = _seed_pair(db_session)
    result = _finalize_shipping_leaves(db_session, project, [leaf1, leaf2])
    req = result["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req.request_number))

    # No inventory was seeded: an OPENING_ITEM line claims nothing from fungible stock, so a pure
    # fetch pull is picked the moment it is confirmed with nothing (#367).
    result = pick_pull(db_session, pr.id, "puller")
    assert result.outcome == "PICKED"
    assert result.shortfalls == []
    assert result.applied_quantity == 0
    assert pr.status == PullRequestStatus.IN_PROGRESS
    assert pr.picked_at is not None

    warehouse_repository.complete_pull_request(db_session, pr.id)
    db_session.flush()
    db_session.refresh(leaf1)
    db_session.refresh(leaf2)
    assert leaf1.state == OpeningItemState.SHIP_READY
    assert leaf2.state == OpeningItemState.SHIP_READY


def test_finalize_rejects_opening_item_line_without_an_opening_item(db_session):
    """An OPENING_ITEM line with no OpeningItem is inert downstream, so it never gets persisted."""
    project = _make_project(db_session)
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [],
                "hardware_items": [],
                "shipping_out_pr_drafts": [
                    {
                        "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                        "requested_by": "importer",
                        "items": [
                            {
                                "item_type": "OPENING_ITEM",
                                "opening_number": "0019-EX",
                                "opening_item_id": None,
                                "requested_quantity": 1,
                            }
                        ],
                    }
                ],
            },
        )
    assert excinfo.value.field == "opening_item_id"
    assert "0019-EX" in excinfo.value.message


def test_finalize_rejects_opening_item_from_another_project(db_session):
    """The client sends the OpeningItem id, so the id is checked against the row, not trusted."""
    _, other_leaf, _ = _seed_pair(db_session)
    stranger = _make_project(db_session)
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_shipping_leaves(db_session, stranger, [other_leaf])
    assert excinfo.value.field == "opening_item_id"
    assert "does not belong to this project" in excinfo.value.message


def test_finalize_rejects_a_leaf_that_is_no_longer_in_inventory(db_session):
    """A leaf already pulled or shipped cannot be requested again by a stale wizard tab."""
    project, leaf1, _ = _seed_pair(db_session)
    leaf1.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_shipping_leaves(db_session, project, [leaf1])
    assert excinfo.value.field == "opening_item_id"
    assert "Leaf 1" in excinfo.value.message
    assert "SHIPPED_OUT" in excinfo.value.message


def test_complete_never_walks_a_shipped_leaf_back_to_ship_ready(db_session):
    """Completing a stale pull must not resurrect a leaf that has already gone out the door."""
    project, leaf1, leaf2 = _seed_pair(db_session)
    result = _finalize_shipping_leaves(db_session, project, [leaf1, leaf2])
    req = result["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == req.request_number))
    pick_pull(db_session, pr.id, "puller")
    db_session.flush()

    # Leaf 1 ships out from an earlier slip while this pull is still open.
    leaf1.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    warehouse_repository.complete_pull_request(db_session, pr.id)
    db_session.flush()
    db_session.refresh(leaf1)
    db_session.refresh(leaf2)
    # Shipped leaf stays shipped; the untouched one still completes normally.
    assert leaf1.state == OpeningItemState.SHIPPED_OUT
    assert leaf2.state == OpeningItemState.SHIP_READY


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

    # Warehouse approves the pull (deducts inventory, PR -> IN_PROGRESS). Reopen must now refuse.
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

    # The warehouse starts the pull on one of them (PR -> IN_PROGRESS): it drops out of the reopen window.
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


# --- REQ-5 assembled-opening guard -----------------------------------------------------------


def test_start_task_rejects_already_assembled_opening(db_session):
    project = _make_project(db_session)
    db_session.flush()
    # Persist opening A01 first.
    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [{"opening_number": "A01"}], "hardware_items": []},
    )
    db_session.flush()
    a01 = db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))

    # An assembled OpeningItem for A01 (state != SHIPPED_OUT) blocks sending it to shop assembly.
    db_session.add(
        OpeningItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=a01.id,
            warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(db_session),
            opening_number="A01",
            quantity=1,
            assembly_completed_at=datetime.utcnow(),
            state=OpeningItemState.IN_INVENTORY,
        )
    )
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_shop_assembly(db_session, project, opening_number="A01")
    assert "A01" in excinfo.value.message
    assert "already assembled" in excinfo.value.message


def test_start_task_allows_shipped_out_opening(db_session):
    """A SHIPPED_OUT OpeningItem does NOT block a new shop-assembly task for the same opening."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    db_session.flush()
    import_repository.finalize_import_session(
        db_session,
        {"project_id": str(project.id), "openings": [{"opening_number": "A01"}], "hardware_items": []},
    )
    db_session.flush()
    a01 = db_session.scalar(select(Opening).where(Opening.project_id == project.id, Opening.opening_number == "A01"))
    db_session.add(
        OpeningItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=a01.id,
            warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(db_session),
            opening_number="A01",
            quantity=1,
            assembly_completed_at=datetime.utcnow(),
            state=OpeningItemState.SHIPPED_OUT,
        )
    )
    db_session.flush()

    result = _finalize_shop_assembly(db_session, project, opening_number="A01")
    db_session.flush()
    assert result["shop_assembly_request"] is not None
