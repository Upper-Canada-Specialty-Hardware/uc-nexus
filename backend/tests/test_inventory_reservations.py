"""Inventory reservations: the claim a holder has between committing to stock and the pull (#342).

Covers the whole lifecycle table in `warehouse/reservations.py` - reserve on create (shipping out)
and on batching (shop assembly, #646), the availability arithmetic including deficient units and
other holders' claims, release on reject and on discard, hold across a reopen, consumption at the
pick with self-coverage, and the degenerate-request guards and re-upload policy that ship with them.

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ConflictError, InventoryShortfallError, ValidationError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
    ShippingOutRequestStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shipping_out_request import ShippingOutRequest
from app.models.shop_assembly import ShopAssemblyRequestItem
from app.models.stock_item import StockItem
from app.repositories import (
    import_repository,
    shipping_repository,
    shop_assembly_repository,
    warehouse_admin_repository,
)
from app.repositories import warehouse as warehouse_repository
from tests.pick_helpers import pick_pull
from tests.shop_assembly_helpers import batch_pull, batch_request

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


def _finalize_sar(session, project, *, qty=2, code="HG-100", opening_number="A01", items=None):
    """Raise a shop-assembly request through the real creation path. Reserves nothing (#646) - use
    `_batched_sar` when the test needs a claim."""
    sa_items = items or [
        {
            "opening_number": opening_number,
            "hardware_category": "HINGE",
            "product_code": code,
            "quantity": qty,
        }
    ]
    numbers = sorted({i["opening_number"] for i in sa_items if i.get("opening_number")})
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": n} for n in numbers],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": sa_items,
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


def _batched_sar(session, project, **kwargs):
    """A shop-assembly request raised and immediately dispatched whole - the shape most of these
    tests want, since a request on its own holds nothing (#646). Returns (request, batch)."""
    sar = _finalize_sar(session, project, **kwargs)["shop_assembly_request"]
    session.flush()
    batch = batch_request(session, sar.id)
    session.flush()
    return sar, batch


def test_raising_a_shop_assembly_request_holds_nothing(db_session):
    """Creation is a flag, not a claim (#646): the shop may need these doors months before the
    hardware is on a shelf, so nothing is reserved and no gate is applied."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=1)

    _finalize_sar(db_session, project, qty=9)
    db_session.flush()

    assert _reservations(db_session, project.id) == []
    assert warehouse_repository.get_project_availability(db_session, project.id)[0]["available_quantity"] == 1


def test_batching_reserves_one_row_per_combo_against_the_batch(db_session):
    """Reservations are aggregate: five lines naming the same hinge hold one row for the total, not
    five rows every availability sum then has to add back up. The holder is the BATCH, so cancelling
    one batch's pull cannot drop a sibling's claim."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)

    _sar, batch = _batched_sar(
        db_session,
        project,
        items=[
            {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3},
            {"opening_number": "A02", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 4},
        ],
    )

    rows = _reservations(db_session, project.id)
    assert len(rows) == 1
    assert rows[0].quantity == 7
    assert rows[0].source == ReservationSource.SHOP_ASSEMBLY_BATCH
    assert rows[0].shop_assembly_batch_id == batch.id
    assert rows[0].shipping_out_request_id is None


def test_creation_is_gated_on_what_other_requests_have_already_claimed(db_session):
    """The second creator sees the first holder's claim, not the raw shelf count."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _batched_sar(db_session, project, qty=4, opening_number="A01")

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
    _batched_sar(db_session, project, qty=2)

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
    _batched_sar(db_session, project, qty=3)

    row = warehouse_repository.get_project_availability(db_session, project.id)[0]
    assert (row["on_hand_quantity"], row["reserved_quantity"], row["available_quantity"]) == (3, 3, 0)


# --- release / hold ----------------------------------------------------------------------------


def test_rejecting_an_unbatched_shop_assembly_request_has_nothing_to_release(db_session):
    """Not an omission (#646): a request with no batches has never held a claim, and one with
    batches cannot be rejected at all."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    sar = _finalize_sar(db_session, project, qty=3)["shop_assembly_request"]
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 0

    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "rejector", "not needed")
    db_session.flush()

    assert _reserved_total(db_session, project.id) == 0
    assert warehouse_repository.check_inventory_sufficiency(
        db_session, project.id, [("HINGE", "HG-100", 5)], reservation_aware=True
    ).sufficient


def test_discarding_a_batch_releases_exactly_that_batchs_claim(db_session):
    """The #325 reopen at batch granularity. A sibling batch's claim must survive it, which is the
    whole reason the holder is the batch rather than the request."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(
        db_session,
        project,
        items=[
            {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3},
            {"opening_number": "A02", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 5},
        ],
    )["shop_assembly_request"]
    db_session.flush()
    keep = batch_request(db_session, sar.id, openings=["A01"])
    drop = batch_request(db_session, sar.id, openings=["A02"])
    db_session.flush()
    assert _reserved_total(db_session, project.id) == 8

    shop_assembly_repository.discard_shop_assembly_batch(db_session, drop.id)
    db_session.flush()

    assert _reserved_total(db_session, project.id) == 3  # only A01's batch is still holding
    # And the 3 that survive are entirely the kept batch's - nothing of the discarded one lingers.
    assert (
        warehouse_repository.get_reserved_quantities(
            db_session,
            project.id,
            [("HINGE", "HG-100")],
            exclude_source=ReservationSource.SHOP_ASSEMBLY_BATCH,
            exclude_request_id=keep.id,
        )
        == {}
    )


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
    _sar, batch = _batched_sar(db_session, project, qty=3)  # reserves all 3

    result = pick_pull(db_session, batch.pull_request_id, "warehouse")

    assert result.outcome == "PICKED"
    assert result.shortfalls == []
    assert il.quantity == 0  # the dictated row gave up its units
    assert _reserved_total(db_session, project.id) == 0  # the claim became the deduction


def test_approval_consumes_a_shipping_out_claim(db_session):
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=4)
    req = _finalize_shipping_loose(db_session, project, qty=4)["shipping_out_requests"][0]
    db_session.flush()
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    pr = db_session.scalar(select(PullRequest).where(PullRequest.id == req.pull_request_id))
    result = pick_pull(db_session, pr.id, "warehouse")

    assert result.outcome == "PICKED"
    assert il.quantity == 0
    assert _reserved_total(db_session, project.id) == 0


def test_a_short_pick_keeps_the_un_picked_part_of_the_claim(db_session):
    """Stock written off under a live claim: the pick comes up short, and the units it could not
    find must NOT be handed to whoever asks next - so that part of the reservation survives.

    Since #367 the consumption is per combo and partial (it used to be all-or-nothing at approve),
    so what remains claimed is exactly what remains owed."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=3)
    _sar, batch = _batched_sar(db_session, project, qty=3)

    il.quantity = 1  # an admin override under the claim
    db_session.flush()

    result = pick_pull(db_session, batch.pull_request_id, "warehouse")

    assert result.outcome == "SHORT"
    assert result.shortfalls[0].short == 2
    assert result.notification is not None
    # 1 was picked and consumed; the 2 it could not find stay claimed for this request.
    assert _reserved_total(db_session, project.id) == 2


def test_a_pull_with_no_claim_cannot_pick_stock_somebody_else_reserved(db_session):
    """The reservation book outranks what is physically reachable (#367), and this is the case that
    proves it.

    An unreserved pull - a PR-REPL replacement that could only partly reserve, or one from the #342
    backfill population - is refused even though the units are sitting there and countable. That is
    the whole point of the table: a claim that only holds until somebody physically gets to the shelf
    first is not a claim, and the request that reserved these units would otherwise discover the loss
    as a short pick on its own pull.

    The picker is not left guessing. The refusal names the combo and how much is claimable, and
    `get_pick_sheet` puts the same number on the screen and the printed sheet before the walk."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=5)
    _batched_sar(db_session, project, qty=4)  # claims 4 of the 5

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
            opening_number="A01",
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=2,
        )
    )
    db_session.flush()

    assert warehouse_repository.find_reservation_holder(db_session, repl) is None

    # Only 1 of the 5 is genuinely free; the pull wants 2.
    sheet = warehouse_repository.get_pick_sheet(db_session, repl.id)
    assert sheet.sections[0].claimable_quantity == 1
    assert sheet.sections[0].claimable_shortfall == 1

    with pytest.raises(ConflictError, match="already claimed this stock"):
        pick_pull(db_session, repl.id, "warehouse")

    # Nothing moved, and the other request still holds exactly what it reserved.
    assert il.quantity == 5
    assert _reserved_total(db_session, project.id) == 4


def test_the_gate_excludes_the_pulls_own_claim(db_session):
    """Self-coverage, at the one moment it decides something. A request that reserved exactly what it
    needs must still be able to pick it - counting its own claim as competing demand would make a
    correctly-reserved request permanently unpickable, which is the failure the exclusion exists to
    prevent."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=3)
    _sar, batch = _batched_sar(db_session, project, qty=3)  # reserves all 3
    pr = batch_pull(db_session, batch)

    # Every unit on the shelf is claimed, but all of it is claimed by this very pull.
    assert warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0].claimable_quantity == 3

    result = pick_pull(db_session, pr.id, "warehouse")

    assert result.outcome == "PICKED"
    assert il.quantity == 0


def test_a_zero_line_shop_assembly_request_is_refused(db_session):
    project = _make_project(db_session)
    with pytest.raises(ValidationError) as excinfo:
        import_repository.finalize_import_session(
            db_session,
            {
                "project_id": str(project.id),
                "openings": [{"opening_number": "A01"}],
                "hardware_items": [],
                "include_shop_assembly_request": True,
                "shop_assembly_items": [],
            },
        )
    assert excinfo.value.field == "shop_assembly_items"
    assert "at least one line" in excinfo.value.message


def test_a_batch_with_nothing_allocated_is_refused(db_session):
    """A batch with no lines is an empty cart: nothing to pull, nothing to reserve, and a pull with
    no lines the warehouse can only close. The openings stay pending instead."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=0)
    sar = _finalize_sar(db_session, project, qty=2)["shop_assembly_request"]
    db_session.flush()

    with pytest.raises(ValidationError) as excinfo:
        shop_assembly_repository.create_shop_assembly_batch(db_session, sar.id, [], created_by="manager")
    assert excinfo.value.field == "lines"

    db_session.refresh(sar, attribute_names=["openings"])
    assert [o.status for o in sar.openings] == [ShopAssemblyOpeningStatus.PENDING]


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


def test_reupload_drops_vanished_openings_from_a_pending_request(db_session):
    """The re-upload is not blocked. A PENDING request is rewritten to what survived - openings and
    their lines both. There is no claim to rebuild: a pending opening never held one (#646)."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(
        db_session,
        project,
        items=[
            {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3},
            {"opening_number": "A02", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 5},
        ],
    )["shop_assembly_request"]
    db_session.flush()

    _reupload(db_session, project, ["A01"])  # A02 is gone from the new schedule
    db_session.flush()
    db_session.refresh(sar, attribute_names=["items", "openings"])

    assert _reserved_total(db_session, project.id) == 0
    remaining = db_session.scalars(
        select(ShopAssemblyRequestItem).where(ShopAssemblyRequestItem.shop_assembly_request_id == sar.id)
    ).all()
    assert [i.opening_number for i in remaining] == ["A01"]
    assert [o.opening_number for o in sar.openings] == ["A01"]
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


def test_reupload_closes_out_a_part_batched_request_that_lost_the_rest(db_session):
    """Some of it genuinely happened, so it closes out rather than being rejected as though it had
    not - and the batched opening keeps its pull and its claim."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(
        db_session,
        project,
        items=[
            {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 3},
            {"opening_number": "A02", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 5},
        ],
    )["shop_assembly_request"]
    db_session.flush()
    batch_request(db_session, sar.id, openings=["A01"])
    db_session.flush()

    _reupload(db_session, project, ["A01"])  # A02, still pending, is gone
    db_session.flush()
    db_session.refresh(sar, attribute_names=["openings"])

    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    assert [(o.opening_number, o.status) for o in sar.openings] == [("A01", ShopAssemblyOpeningStatus.BATCHED)]
    assert _reserved_total(db_session, project.id) == 3


def test_reupload_flags_a_surviving_request(db_session):
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


def test_reupload_leaves_a_batched_openings_pull_alone(db_session):
    """Once the pull exists it is the authority on what the warehouse will hand over; shrinking it
    underneath the puller would be worse than a stale bill of hardware. Flag only."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _finalize_sar(db_session, project, qty=4, opening_number="A01")["shop_assembly_request"]
    db_session.flush()
    batch_request(db_session, sar.id)
    db_session.flush()

    _reupload(db_session, project, ["Z99"])  # A01 is gone
    db_session.flush()
    db_session.refresh(sar, attribute_names=["items", "openings"])

    assert sar.status == ShopAssemblyRequestStatus.APPROVED
    assert sar.integrity_note is not None
    assert _reserved_total(db_session, project.id) == 4
    assert [o.status for o in sar.openings] == [ShopAssemblyOpeningStatus.BATCHED]
    assert (
        db_session.scalars(
            select(ShopAssemblyRequestItem).where(ShopAssemblyRequestItem.shop_assembly_request_id == sar.id)
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
                            "opening_number": "A01",
                            "hardware_category": "HINGE",
                            "product_code": "HG-100",
                            "requested_quantity": 2,
                        },
                        {
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


def test_the_exclusion_is_what_makes_a_fully_reserved_holder_pickable(db_session):
    """Directly: without excluding its own claim, a batch that reserved exactly what it needs would
    read as competing with itself and could never be picked."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)
    _sar, batch = _batched_sar(db_session, project, qty=3)

    needs = [("HINGE", "HG-100", 3)]
    without = warehouse_repository.check_inventory_sufficiency(db_session, project.id, needs, reservation_aware=True)
    assert not without.sufficient

    with_self = warehouse_repository.check_inventory_sufficiency(
        db_session,
        project.id,
        needs,
        reservation_aware=True,
        exclude_reservations_of=(ReservationSource.SHOP_ASSEMBLY_BATCH, batch.id),
    )
    assert with_self.sufficient


def test_release_is_idempotent(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _sar, batch = _batched_sar(db_session, project, qty=2)

    assert warehouse_repository.release_reservations(db_session, ReservationSource.SHOP_ASSEMBLY_BATCH, batch.id) == 1
    assert warehouse_repository.release_reservations(db_session, ReservationSource.SHOP_ASSEMBLY_BATCH, batch.id) == 0
    assert _reservations(db_session, project.id) == []


def test_reservations_are_scoped_to_their_project(db_session):
    """A claim in one project cannot make stock look unavailable in another - inventory is
    project-scoped and so is the claim on it."""
    project_a = _make_project(db_session)
    project_b = _make_project(db_session)
    _seed_inventory(db_session, project_a.id, quantity=5)
    _seed_inventory(db_session, project_b.id, quantity=5)
    _batched_sar(db_session, project_a, qty=5)

    assert _reserved_total(db_session, project_a.id) == 5
    assert _reserved_total(db_session, project_b.id) == 0
    assert warehouse_repository.check_inventory_sufficiency(
        db_session, project_b.id, [("HINGE", "HG-100", 5)], reservation_aware=True
    ).sufficient


def test_self_coverage_excludes_only_that_holder_not_the_other_source(db_session):
    """`exclude_reservations_of` names a single holder. Written as `column != id` it silently
    dropped every row of the *opposite* source too, because that column is NULL on those rows and
    `NULL != id` is NULL - so the cross-type guarantee the table exists for was void."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    _sar, batch = _batched_sar(db_session, project, qty=3)
    sor = _finalize_shipping_loose(db_session, project, qty=2, opening_number="A02")["shipping_out_requests"][0]
    db_session.flush()

    assert _reserved_total(db_session, project.id) == 5

    # Excluding the shop-assembly batch must leave the shipping-out claim standing, and vice versa.
    assert warehouse_repository.get_reserved_quantities(
        db_session,
        project.id,
        [("HINGE", "HG-100")],
        exclude_source=ReservationSource.SHOP_ASSEMBLY_BATCH,
        exclude_request_id=batch.id,
    ) == {("HINGE", "HG-100"): 2}
    assert warehouse_repository.get_reserved_quantities(
        db_session,
        project.id,
        [("HINGE", "HG-100")],
        exclude_source=ReservationSource.SHIPPING_OUT_REQUEST,
        exclude_request_id=sor.id,
    ) == {("HINGE", "HG-100"): 3}


def test_the_cross_type_exclusion_is_what_the_creation_gate_reads(db_session):
    """End to end: a shop-assembly request created while a shipping-out request holds part of the
    shelf sees only what is genuinely free.

    This used to be asserted through pull approval, which was the gate. Since #367 the pull is not
    gated on an aggregate at all - the picker names rows - so the assertion moved to the arithmetic
    itself, which is where the cross-type guarantee actually lives."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=5)
    _sar, batch = _batched_sar(db_session, project, qty=3)
    _finalize_shipping_loose(db_session, project, qty=2, opening_number="A02")
    db_session.flush()

    # A unit is condemned under the two live claims, so 4 are on hand and 2 are spoken for.
    il.deficient_quantity = 1
    db_session.flush()

    result = warehouse_repository.check_inventory_sufficiency(
        db_session,
        project.id,
        [("HINGE", "HG-100", 3)],
        reservation_aware=True,
        exclude_reservations_of=(ReservationSource.SHOP_ASSEMBLY_BATCH, batch.id),
    )

    assert not result.sufficient
    shortfalls = result.shortfalls
    assert [(s.product_code, s.available, s.short, s.reserved) for s in shortfalls] == [("HG-100", 2, 1, 2)]
    assert il.quantity == 5  # nothing deducted


def test_an_unreserved_holder_that_comes_up_short_is_not_an_integrity_error(db_session):
    """The #342 backfill deliberately left the pre-existing in-flight population unreserved and
    flagged. Those requests are the *expected* shortfall case; auditing every one of them as
    RESERVED_PULL_SHORT is how a real one would get missed."""
    from app.models.audit_log import InventoryAuditLog

    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=3)
    _sar, batch = _batched_sar(db_session, project, qty=3)
    # Strip the claim, exactly as a backfill-era holder holds none.
    warehouse_repository.release_reservations(db_session, ReservationSource.SHOP_ASSEMBLY_BATCH, batch.id)
    db_session.flush()

    # Now the stock goes away under it.
    il = db_session.scalar(select(InventoryLocation).where(InventoryLocation.project_id == project.id))
    il.quantity = 1
    db_session.flush()

    pr = batch_pull(db_session, batch)
    result = pick_pull(db_session, pr.id, "warehouse")

    assert result.outcome == "SHORT"
    integrity_rows = [
        row
        for row in db_session.scalars(select(InventoryAuditLog).where(InventoryAuditLog.entity_id == pr.id)).all()
        if (row.detail or {}).get("integrityError") == "RESERVED_PULL_SHORT"
    ]
    assert integrity_rows == []


def test_a_holder_that_really_does_hold_a_claim_still_records_the_integrity_error(db_session):
    """The other half: a request that *is* reserved is not supposed to be able to come up short, so
    when it does the discrepancy stays investigable."""
    from app.models.audit_log import InventoryAuditLog

    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=3)
    _sar, batch = _batched_sar(db_session, project, qty=3)

    il.quantity = 1  # written off under a live claim
    db_session.flush()

    pr = batch_pull(db_session, batch)
    result = pick_pull(db_session, pr.id, "warehouse")

    assert result.outcome == "SHORT"
    integrity_rows = [
        row
        for row in db_session.scalars(select(InventoryAuditLog).where(InventoryAuditLog.entity_id == pr.id)).all()
        if (row.detail or {}).get("integrityError") == "RESERVED_PULL_SHORT"
    ]
    assert len(integrity_rows) == 1
