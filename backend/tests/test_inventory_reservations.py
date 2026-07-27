"""Inventory reservations: the claim a request holds between creation and the pull (#342).

Covers the whole lifecycle table in `warehouse/reservations.py` - reserve on create (both request
types), the availability arithmetic including deficient units and other requests' claims, release on
reject, hold across a reopen, consumption at pull approval with self-coverage, the PR-REPL pull that
holds no claim but must still respect everyone else's, and the request-integrity guards
(duplicate/degenerate/cross-type) and re-upload policy that ship with them.

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InventoryShortfallError, ValidationError
from app.models.enums import (
    AssemblyStatus,
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.opening_item import OpeningItem, OpeningItemHardware
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shipping_out_request import ShippingOutRequest
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem, ShopAssemblyRequest
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    shop_assembly_repository,
    warehouse_admin_repository,
)
from app.repositories import warehouse as warehouse_repository

# --- fixtures / helpers ------------------------------------------------------------------------


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
        row="1",
        bay="1",
        received_at=received_at or datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _reservations(session, project_id):
    return list(
        session.scalars(select(InventoryReservation).where(InventoryReservation.project_id == project_id)).all()
    )


def _reserved_total(session, project_id, category="HINGE", code="HG-100"):
    return warehouse_repository.get_reserved_quantities(session, project_id).get((category, code), 0)


def _finalize_sar(session, project, *, qty=2, code="HG-100", opening_number="A01", leaf=None, openings=None):
    """Create a shop-assembly request through the real creation path (which is where the gate is)."""
    sa_openings = openings or [
        {
            "opening_number": opening_number,
            "leaf": leaf,
            "items": [{"hardware_category": "HINGE", "product_code": code, "quantity": qty}],
        }
    ]
    numbers = sorted({o["opening_number"] for o in sa_openings})
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": n} for n in numbers],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": sa_openings,
        },
    )


def _finalize_shipping_loose(session, project, *, qty=2, code="HG-100", opening_number="A01"):
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


def _make_assembled_leaf(session, project, opening, *, leaf, code="HG-100", category="HINGE"):
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


def _finalize_shipping_leaves(session, project, opening_items):
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
                            "leaf": oi.leaf,
                            "requested_quantity": 1,
                        }
                        for oi in opening_items
                    ],
                }
            ],
        },
    )


# --- reserve on create -------------------------------------------------------------------------


def test_shop_assembly_creation_reserves_one_row_per_combo(db_session):
    """Reservations are aggregate: five openings naming the same hinge hold one row for the total,
    not five rows every availability sum then has to add back up."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)

    result = _finalize_sar(
        db_session,
        project,
        openings=[
            {
                "opening_number": "A01",
                "leaf": 1,
                "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3}],
            },
            {
                "opening_number": "A01",
                "leaf": 2,
                "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 4}],
            },
        ],
    )
    db_session.flush()

    rows = _reservations(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].quantity == 7
    assert rows[0].source == ReservationSource.SHOP_ASSEMBLY_REQUEST
    assert rows[0].shop_assembly_request_id == result["shop_assembly_request"].id
    assert rows[0].shipping_out_request_id is None


def test_shipping_out_loose_lines_reserve_and_opening_item_lines_do_not(db_session):
    """A LOOSE line claims fungible stock. An assembled leaf claimed its hardware at assembly and
    ships as itself, so an OPENING_ITEM line reserves nothing at all."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    result = _finalize_shipping_loose(db_session, project, qty=4)
    db_session.flush()

    rows = _reservations(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].quantity == 4
    assert rows[0].source == ReservationSource.SHIPPING_OUT_REQUEST
    assert rows[0].shipping_out_request_id == result["shipping_out_requests"][0].id

    # Now an OPENING_ITEM-only request in the same project: no new claim.
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="B02")
    db_session.add(opening)
    db_session.flush()
    leaf = _make_assembled_leaf(db_session, project, opening, leaf=1)
    _finalize_shipping_leaves(db_session, project, [leaf])
    db_session.flush()

    assert len(_reservations(db_session, project.id)) == 1


def test_creation_is_gated_on_what_other_requests_have_already_claimed(db_session):
    """The second creator sees the first creator's claim, not the raw shelf count."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _finalize_sar(db_session, project, qty=4, opening_number="A01")
    db_session.flush()

    with pytest.raises(InventoryShortfallError) as excinfo:
        _finalize_shipping_loose(db_session, project, qty=2, opening_number="A02")

    s = excinfo.value.shortfalls[0]
    assert (s.requested, s.available, s.reserved, s.short) == (2, 1, 4, 1)


def test_availability_nets_deficient_units_without_double_counting(db_session):
    """A deficiency reported at the bench bumps the inventory row's quantity AND deficient_quantity
    together, so it nets to zero in the availability sum - the condemned unit is back in the
    building, is not available, and is not counted twice against a reservation."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=6)
    _finalize_sar(db_session, project, qty=2)
    db_session.flush()

    before = warehouse_repository.get_project_availability(db_session, project.id)[0]
    assert (before["on_hand_quantity"], before["deficient_quantity"], before["reserved_quantity"]) == (6, 0, 2)
    assert before["available_quantity"] == 4

    # A unit comes back condemned: quantity 6 -> 7, deficient 0 -> 1.
    il.quantity += 1
    il.deficient_quantity += 1
    db_session.flush()

    after = warehouse_repository.get_project_availability(db_session, project.id)[0]
    assert (after["on_hand_quantity"], after["deficient_quantity"], after["reserved_quantity"]) == (7, 1, 2)
    assert after["available_quantity"] == 4  # unchanged - the return was a wash


def test_availability_lists_a_fully_claimed_combo_rather_than_hiding_it(db_session):
    """available floors at 0, and a combo whose stock is entirely spoken for still appears - a
    creator has to be able to see WHY it reads zero."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)
    _finalize_sar(db_session, project, qty=3)
    db_session.flush()

    row = warehouse_repository.get_project_availability(db_session, project.id)[0]
    assert (row["on_hand_quantity"], row["reserved_quantity"], row["available_quantity"]) == (3, 3, 0)


# --- release / hold ----------------------------------------------------------------------------


def test_reject_releases_a_shop_assembly_claim(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_sar(db_session, project, qty=3)["shop_assembly_request"]
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 3

    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "not needed")
    db_session.flush()

    assert _reserved_total(db_session, project.id) == 0
    # And the hardware is claimable again.
    assert warehouse_repository.check_inventory_sufficiency(
        db_session, project.id, [("HINGE", "HG-100", 5)], reservation_aware=True
    ).sufficient


def test_reopen_keeps_the_claim_and_rejecting_afterwards_releases_it(db_session):
    """Reopen (#325) undoes the ACCEPT, not the creation. The request goes back to PENDING still
    holding what it reserved at creation - releasing here would let a second request grab the
    hardware while the first is still on the board waiting to be re-accepted."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_sar(db_session, project, qty=3)["shop_assembly_request"]
    db_session.flush()

    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 3  # accept neither spends nor releases

    shop_assembly_repository.reopen_shop_assembly_request(db_session, sar.id)
    db_session.flush()
    assert db_session.get(ShopAssemblyRequest, sar.id).status == ShopAssemblyRequestStatus.PENDING
    assert _reserved_total(db_session, project.id) == 3  # still holding

    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "mistake")
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 0  # the reject is what finally lets go


def test_reopen_keeps_a_shipping_out_claim_too(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    req = _finalize_shipping_loose(db_session, project, qty=2)["shipping_out_requests"][0]
    db_session.flush()

    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    shipping_repository.reopen_shipping_out_request(db_session, req.id)
    db_session.flush()

    assert db_session.get(ShippingOutRequest, req.id).status == ShippingOutRequestStatus.PENDING
    assert _reserved_total(db_session, project.id) == 2

    shipping_repository.reject_shipping_out_request(db_session, req.id, "rejector", None)
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 0


# --- consumption at pull approval --------------------------------------------------------------


def test_approval_consumes_the_requests_own_claim_and_deducts(db_session):
    """Self-coverage: the request's own reservation backs the deduction, so the availability check
    on this path must not count it against the request. A fully-reserved request that took the last
    of the stock still approves."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=3)
    sar = _finalize_sar(db_session, project, qty=3)["shop_assembly_request"]  # reserves all 3
    db_session.flush()
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    _, outcome, _, shortfalls = warehouse_repository.approve_pull_request(db_session, pr.id, "warehouse")
    db_session.flush()

    assert outcome == "APPROVED"
    assert shortfalls == []
    assert il.quantity == 0  # deducted FIFO, unchanged behaviour
    assert _reserved_total(db_session, project.id) == 0  # the claim became the deduction


def test_approval_consumes_a_shipping_out_claim(db_session):
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=4)
    req = _finalize_shipping_loose(db_session, project, qty=4)["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.id == req.pull_request_id))
    _, outcome, _, _ = warehouse_repository.approve_pull_request(db_session, pr.id, "warehouse")
    db_session.flush()

    assert outcome == "APPROVED"
    assert il.quantity == 0
    assert _reserved_total(db_session, project.id) == 0


def test_a_blocked_approval_keeps_the_claim(db_session):
    """Stock written off under a live claim: the pull is short, stays PENDING, and must NOT hand its
    hardware to whoever asks next - so the reservation survives the failed attempt."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=3)
    sar = _finalize_sar(db_session, project, qty=3)["shop_assembly_request"]
    db_session.flush()
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    il.quantity = 1  # an admin override under the claim
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    _, outcome, notif, shortfalls = warehouse_repository.approve_pull_request(db_session, pr.id, "warehouse")
    db_session.flush()

    assert outcome == "INSUFFICIENT"
    assert shortfalls[0].short == 2
    assert notif is not None
    assert _reserved_total(db_session, project.id) == 3


def test_a_replacement_pull_holds_no_claim_but_respects_everyone_elses(db_session):
    """A PR-REPL pull is unreserved by nature - nobody can reserve for a deficiency that has not
    happened yet - so it keeps the reactive check. What it must not do is eat stock another request
    has already claimed."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _finalize_sar(db_session, project, qty=4)  # claims 4 of the 5
    db_session.flush()

    repl = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-REPL-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by="assembler",
    )
    db_session.add(repl)
    db_session.flush()
    db_session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=repl.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number="A01",
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=2,
        )
    )
    db_session.flush()

    assert warehouse_repository.find_reservation_holder(db_session, repl) is None

    _, outcome, _, shortfalls = warehouse_repository.approve_pull_request(db_session, repl.id, "warehouse")
    db_session.flush()

    assert outcome == "INSUFFICIENT"
    assert (shortfalls[0].available, shortfalls[0].reserved) == (1, 4)
    # The other request's claim is untouched by the blocked replacement pull.
    assert _reserved_total(db_session, project.id) == 4


def test_a_replacement_pull_approves_out_of_what_is_genuinely_free(db_session):
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=5)
    _finalize_sar(db_session, project, qty=3)
    db_session.flush()

    repl = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-REPL-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by="assembler",
    )
    db_session.add(repl)
    db_session.flush()
    db_session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=repl.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number="A01",
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=2,
        )
    )
    db_session.flush()

    _, outcome, _, _ = warehouse_repository.approve_pull_request(db_session, repl.id, "warehouse")
    db_session.flush()

    assert outcome == "APPROVED"
    assert il.quantity == 3
    assert _reserved_total(db_session, project.id) == 3  # the other request still holds its 3


# --- request-integrity guards ------------------------------------------------------------------


def test_a_leaf_in_a_live_shop_assembly_request_cannot_be_requested_again(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    first = _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)["shop_assembly_request"]
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)
    assert excinfo.value.field == "shop_assembly_openings"
    assert first.request_number in excinfo.value.message


def test_the_in_flight_guard_is_per_leaf(db_session):
    """Requesting Leaf 1 must not block Leaf 2 - the same rule the already-assembled guard uses."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _finalize_sar(db_session, project, qty=2, opening_number="PR1", leaf=1)
    db_session.flush()

    _finalize_sar(db_session, project, qty=2, opening_number="PR1", leaf=2)
    db_session.flush()

    assert _reserved_total(db_session, project.id) == 4


def test_a_rejected_request_stops_blocking_its_leaf(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)["shop_assembly_request"]
    db_session.flush()
    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", None)
    db_session.flush()

    _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 2


def test_a_completed_work_unit_no_longer_counts_as_in_flight(db_session):
    """A COMPLETED opening is the already-assembled guard's business, not this one's - otherwise the
    two guards would give the same leaf two different refusals."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)
    db_session.flush()
    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.opening_number == "A01"))
    sao.assembly_status = AssemblyStatus.COMPLETED
    db_session.flush()

    opening = db_session.scalar(select(Opening).where(Opening.project_id == project.id))
    specs = [("A01", opening.id, 1)]
    assert shop_assembly_repository.find_in_flight_assembly_leaves(db_session, specs) == []


def test_a_leaf_on_a_live_shipping_request_cannot_be_sent_to_shop_assembly(db_session):
    """Cross-request-type conflict: one physical leaf cannot be both on its way out the door and
    back on the bench."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="A01")
    db_session.add(opening)
    db_session.flush()
    leaf = _make_assembled_leaf(db_session, project, opening, leaf=1)
    ship_req = _finalize_shipping_leaves(db_session, project, [leaf])["shipping_out_requests"][0]
    db_session.flush()
    # Take the assembled unit out of the way so the *already-assembled* guard is not what fires.
    leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)
    assert "shipping-out request" in excinfo.value.message
    assert ship_req.request_number in excinfo.value.message


def test_a_leaf_already_on_a_live_shipping_request_cannot_be_requested_again(db_session):
    project = _make_project(db_session)
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="A01")
    db_session.add(opening)
    db_session.flush()
    leaf = _make_assembled_leaf(db_session, project, opening, leaf=1)
    first = _finalize_shipping_leaves(db_session, project, [leaf])["shipping_out_requests"][0]
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        _finalize_shipping_leaves(db_session, project, [leaf])
    assert excinfo.value.field == "opening_item_id"
    assert first.request_number in excinfo.value.message


def test_a_leaf_still_in_shop_assembly_cannot_be_shipped(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(db_session, project, qty=2, opening_number="A01", leaf=1)["shop_assembly_request"]
    db_session.flush()
    opening = db_session.scalar(select(Opening).where(Opening.project_id == project.id))
    leaf = _make_assembled_leaf(db_session, project, opening, leaf=1)

    with pytest.raises(ValidationError) as excinfo:
        _finalize_shipping_leaves(db_session, project, [leaf])
    assert "still in shop assembly" in excinfo.value.message
    assert sar.request_number in excinfo.value.message


def test_a_zero_opening_shop_assembly_request_is_refused(db_session):
    project = _make_project(db_session)
    with pytest.raises(ValidationError) as excinfo:
        import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [{"opening_number": "A01"}],
                "hardware_items": [],
                "include_shop_assembly_request": True,
                "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
                "shop_assembly_openings": [],
            },
        )
    assert excinfo.value.field == "shop_assembly_openings"
    assert "at least one opening" in excinfo.value.message


def test_a_zero_item_opening_is_refused(db_session):
    """A leaf with an empty checklist would reach shop assembly as something #339 refuses to
    complete, so it never gets created."""
    project = _make_project(db_session)
    with pytest.raises(ValidationError) as excinfo:
        _finalize_sar(
            db_session,
            project,
            openings=[{"opening_number": "A01", "leaf": 2, "items": []}],
        )
    assert excinfo.value.field == "shop_assembly_openings"
    assert "Opening A01 Leaf 2" in excinfo.value.message


def test_a_zero_line_shipping_request_is_refused(db_session):
    project = _make_project(db_session)
    with pytest.raises(ValidationError) as excinfo:
        import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [],
                "hardware_items": [],
                "shipping_out_pr_drafts": [{"request_number": "SHIP-EMPTY", "requested_by": "importer", "items": []}],
            },
        )
    assert excinfo.value.field == "items"
    assert "no items" in excinfo.value.message


# --- schedule re-upload ------------------------------------------------------------------------


def _reupload(session, project, opening_numbers):
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": n} for n in opening_numbers],
            "hardware_items": [],
            "replace_schedule": True,
        },
    )


def test_reupload_drops_vanished_openings_and_releases_their_claim(db_session):
    """The re-upload is not blocked. A PENDING request is rewritten to what survived, and its
    reservation is rebuilt from that - releasing exactly what the vanished opening was holding."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(
        db_session,
        project,
        openings=[
            {
                "opening_number": "A01",
                "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3}],
            },
            {
                "opening_number": "A02",
                "items": [{"hardware_category": "HINGE", "product_code": "HG-100", "quantity": 5}],
            },
        ],
    )["shop_assembly_request"]
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 8

    _reupload(db_session, project, ["A01"])  # A02 is gone from the new schedule
    db_session.flush()
    db_session.refresh(sar)

    assert _reserved_total(db_session, project.id) == 3
    remaining = db_session.scalars(
        select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id)
    ).all()
    assert [o.opening_number for o in remaining] == ["A01"]
    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert sar.integrity_note is not None
    assert "no longer exist" in sar.integrity_note


def test_reupload_auto_rejects_a_request_that_lost_everything(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(db_session, project, qty=4, opening_number="A01")["shop_assembly_request"]
    db_session.flush()

    _reupload(db_session, project, ["Z99"])
    db_session.flush()
    db_session.refresh(sar)

    assert sar.status == ShopAssemblyRequestStatus.REJECTED
    assert sar.rejected_by == "Hardware Schedule Import"
    assert _reserved_total(db_session, project.id) == 0


def test_reupload_flags_a_surviving_request_without_touching_its_claim(db_session):
    """A full-schedule replacement can change the hardware on an opening it kept, so every live
    request is flagged - not just the ones that lost openings."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(db_session, project, qty=4, opening_number="A01")["shop_assembly_request"]
    db_session.flush()

    _reupload(db_session, project, ["A01"])
    db_session.flush()
    db_session.refresh(sar)

    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert sar.integrity_note is not None
    assert "re-uploaded" in sar.integrity_note
    assert _reserved_total(db_session, project.id) == 4


def test_reupload_leaves_an_accepted_requests_pull_alone(db_session):
    """Once the pull exists it is the authority on what the warehouse will hand over; shrinking it
    underneath the puller would be worse than a stale bill of hardware. Flag only."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(db_session, project, qty=4, opening_number="A01")["shop_assembly_request"]
    db_session.flush()
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()

    _reupload(db_session, project, ["Z99"])  # A01 is gone
    db_session.flush()
    db_session.refresh(sar)

    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    assert sar.integrity_note is not None
    assert _reserved_total(db_session, project.id) == 4
    assert (
        db_session.scalars(
            select(ShopAssemblyOpeningItem)
            .join(ShopAssemblyOpening, ShopAssemblyOpeningItem.shop_assembly_opening_id == ShopAssemblyOpening.id)
            .where(ShopAssemblyOpening.shop_assembly_request_id == sar.id)
        ).all()
        != []
    )


def test_reupload_rebuilds_a_shipping_requests_loose_claim(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    req = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "item_type": "LOOSE",
                            "opening_number": "A01",
                            "hardware_category": "HINGE",
                            "product_code": "HG-100",
                            "requested_quantity": 2,
                        },
                        {
                            "item_type": "LOOSE",
                            "opening_number": "A02",
                            "hardware_category": "HINGE",
                            "product_code": "HG-100",
                            "requested_quantity": 6,
                        },
                    ],
                }
            ],
        },
    )["shipping_out_requests"][0]
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 8

    _reupload(db_session, project, ["A01"])
    db_session.flush()
    db_session.refresh(req)

    assert _reserved_total(db_session, project.id) == 2
    assert [i.opening_number for i in req.items] == ["A01"]
    assert req.status == ShippingOutRequestStatus.PENDING


# --- self-coverage at the repository level ------------------------------------------------------


def test_the_exclusion_is_what_makes_a_fully_reserved_request_approvable(db_session):
    """Directly: without excluding its own claim, a request that reserved exactly what it needs
    would read as competing with itself and could never be approved."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)
    sar = _finalize_sar(db_session, project, qty=3)["shop_assembly_request"]
    db_session.flush()

    needs = [("HINGE", "HG-100", 3)]
    without = warehouse_repository.check_inventory_sufficiency(db_session, project.id, needs, reservation_aware=True)
    assert not without.sufficient

    with_self = warehouse_repository.check_inventory_sufficiency(
        db_session,
        project.id,
        needs,
        reservation_aware=True,
        exclude_reservations_of=(ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id),
    )
    assert with_self.sufficient


def test_release_is_idempotent(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_sar(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    assert warehouse_repository.release_reservations(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 1
    assert warehouse_repository.release_reservations(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 0
    assert _reservations(db_session, project.id) == []


def test_reservations_are_scoped_to_their_project(db_session):
    """A claim in one project cannot make stock look unavailable in another - inventory is
    project-scoped and so is the claim on it."""
    project_a = _make_project(db_session)
    project_b = _make_project(db_session)
    _seed_inventory(db_session, project_a.id, quantity=5)
    _seed_inventory(db_session, project_b.id, quantity=5)
    _finalize_sar(db_session, project_a, qty=5)
    db_session.flush()

    assert _reserved_total(db_session, project_a.id) == 5
    assert _reserved_total(db_session, project_b.id) == 0
    assert warehouse_repository.check_inventory_sufficiency(
        db_session, project_b.id, [("HINGE", "HG-100", 5)], reservation_aware=True
    ).sufficient


def test_shop_assembly_openings_still_reach_the_bench_after_a_reserved_pull(db_session):
    """End-to-end sanity: the whole reserve -> accept -> approve -> complete chain still lands the
    opening in PULLED with nothing left reserved."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=4)
    sar = _finalize_sar(db_session, project, qty=4)["shop_assembly_request"]
    db_session.flush()
    shop_assembly_repository.accept_shop_assembly_request(db_session, sar.id, "acceptor")
    db_session.flush()
    pr = db_session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    warehouse_repository.approve_pull_request(db_session, pr.id, "warehouse")
    db_session.flush()
    warehouse_repository.complete_pull_request(db_session, pr.id)
    db_session.flush()

    sao = db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.shop_assembly_request_id == sar.id))
    assert sao.pull_status == PullStatus.PULLED
    assert _reserved_total(db_session, project.id) == 0
