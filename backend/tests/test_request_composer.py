"""The arithmetic both composers read: `suggested = max(owed - sent - claimed, 0)`.

Every term is a different table, and the ways they can be double-counted are the whole reason this
module exists rather than three separate reads in two wizards. What is pinned here:

  - owed is the CURRENT schedule, summed across an opening's leaves
  - a completed shop-assembly pull is `sent`, terminally
  - a completed shipping pull and the slip cut from it are ONE departure, not two
  - a request counts once - as a claim while it is live, as sent once its pull completes, never both
  - a re-upload that lowers owed below sent reads zero, never negative and never a return

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.enums import (
    Classification,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ShipmentStatus,
    ShippingOutRequestStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.models.shop_assembly import ShopAssemblyRequest, ShopAssemblyRequestItem
from app.models.stock_item import StockItem
from app.repositories import request_composer, warehouse_admin_repository

CAT, CODE = "HINGE", "HG-100"


# --- fixtures ----------------------------------------------------------------------------------


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _opening(session, project, number="A01", *, leaf_count=None) -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=number, leaf_count=leaf_count)
    session.add(o)
    session.flush()
    return o


def _owe(session, project, opening, quantity, *, leaf=None, code=CODE, classification=None):
    session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            hardware_category=CAT,
            product_code=code,
            item_quantity=quantity,
            leaf=leaf,
            classification=classification,
        )
    )
    session.flush()


def _pull(session, project, *, source, status, lines):
    """A pull with one line per (opening, quantity)."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=source,
        status=status,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    for opening_number, quantity in lines:
        session.add(
            PullRequestItem(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                opening_number=opening_number,
                hardware_category=CAT,
                product_code=CODE,
                requested_quantity=quantity,
            )
        )
    session.flush()
    return pr


def _slip(session, project, *, lines):
    ps = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.SCHEDULED,
    )
    session.add(ps)
    session.flush()
    for opening_number, quantity in lines:
        session.add(
            PackingSlipItem(
                id=uuid.uuid4(),
                packing_slip_id=ps.id,
                opening_number=opening_number,
                hardware_category=CAT,
                product_code=CODE,
                quantity=quantity,
            )
        )
    session.flush()
    return ps


def _pending_sar(session, project, *, opening_number, quantity):
    req = ShopAssemblyRequest(
        id=uuid.uuid4(),
        request_number=f"SA-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=ShopAssemblyRequestStatus.PENDING,
        created_by="tester",
    )
    session.add(req)
    session.flush()
    session.add(
        ShopAssemblyRequestItem(
            id=uuid.uuid4(),
            shop_assembly_request_id=req.id,
            opening_number=opening_number,
            hardware_category=CAT,
            product_code=CODE,
            quantity=quantity,
            allocated_quantity=quantity,
        )
    )
    session.flush()
    return req


def _pending_sor(session, project, *, opening_number, quantity):
    req = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"SO-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=ShippingOutRequestStatus.PENDING,
        created_by="tester",
    )
    session.add(req)
    session.flush()
    session.add(
        ShippingOutRequestItem(
            id=uuid.uuid4(),
            shipping_out_request_id=req.id,
            opening_number=opening_number,
            hardware_category=CAT,
            product_code=CODE,
            requested_quantity=quantity,
        )
    )
    session.flush()
    return req


def _row(session, project, openings=("A01",), *, code=CODE):
    rows = request_composer.get_request_coverage(session, project.id, list(openings))
    matching = [r for r in rows if r["product_code"] == code]
    assert len(matching) <= 1, matching
    return matching[0] if matching else None


# --- owed ---------------------------------------------------------------------------------------


def test_owed_is_the_current_schedule_summed_across_leaves(db_session):
    """The leaf survives on HardwareItem as parsed demand data and stops propagating here: the
    composer works per opening, so a pair's two leaf rows are one number."""
    project = _project(db_session)
    opening = _opening(db_session, project, leaf_count=2)
    _owe(db_session, project, opening, 3, leaf=1)
    _owe(db_session, project, opening, 4, leaf=2)

    row = _row(db_session, project)
    assert row["owed_quantity"] == 7
    assert row["suggested_quantity"] == 7


def test_an_opening_the_schedule_does_not_list_yields_no_row(db_session):
    project = _project(db_session)
    _opening(db_session, project)

    assert request_composer.get_request_coverage(db_session, project.id, ["A01"]) == []


def test_no_openings_asked_for_is_no_work_done(db_session):
    project = _project(db_session)
    assert request_composer.get_request_coverage(db_session, project.id, []) == []


def test_classification_is_decided_by_unit_count_not_row_order(db_session):
    """Two schedule rows for one product on one opening are free to disagree, so the answer has to
    be decided rather than picked off whichever row came back first."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 1, classification=Classification.SITE_HARDWARE)
    _owe(db_session, project, opening, 5, classification=Classification.SHOP_HARDWARE)

    assert _row(db_session, project)["classification"] == Classification.SHOP_HARDWARE


def test_an_unclassified_majority_answers_none_rather_than_guessing(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 5)
    _owe(db_session, project, opening, 1, classification=Classification.SITE_HARDWARE)

    assert _row(db_session, project)["classification"] is None


# --- sent ---------------------------------------------------------------------------------------


def test_a_completed_shop_assembly_pull_is_sent(db_session):
    """Shop assembly is a terminal exit: the bench work after it is untracked in v1, so the pull is
    the last thing the system sees of that hardware."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 4)],
    )

    row = _row(db_session, project)
    assert row["sent_quantity"] == 4
    assert row["claimed_quantity"] == 0
    assert row["suggested_quantity"] == 2


def test_a_completed_shipping_pull_and_its_slip_are_one_departure(db_session):
    """The slip consumes what the pull fulfilled. Summing would charge the opening twice for one
    shipment; taking only the slip would re-offer everything picked and waiting for a truck."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 10)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 4)],
    )
    _slip(db_session, project, lines=[("A01", 4)])

    row = _row(db_session, project)
    assert row["sent_quantity"] == 4
    assert row["suggested_quantity"] == 6


def test_hardware_picked_but_not_yet_shipped_still_counts_as_sent(db_session):
    """The staged half of the fold. It is off the shelf and on a cart; offering it again would put
    the same units on a second request."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 10)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 4)],
    )

    assert _row(db_session, project)["sent_quantity"] == 4


def test_the_two_exits_add_together(db_session):
    """A shop-assembly pull and a shipping pull are different departures for the same opening, so
    unlike the pull/slip pair they sum."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 10)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 3)],
    )
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 2)],
    )

    row = _row(db_session, project)
    assert row["sent_quantity"] == 5
    assert row["suggested_quantity"] == 5


def test_a_cancelled_pull_sent_nothing(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.CANCELLED,
        lines=[("A01", 4)],
    )

    row = _row(db_session, project)
    assert (row["sent_quantity"], row["claimed_quantity"], row["suggested_quantity"]) == (0, 0, 6)


# --- claimed ------------------------------------------------------------------------------------


def test_a_pending_request_is_a_claim(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    _pending_sar(db_session, project, opening_number="A01", quantity=4)

    row = _row(db_session, project)
    assert (row["sent_quantity"], row["claimed_quantity"], row["suggested_quantity"]) == (0, 4, 2)


def test_a_pending_shipping_request_is_a_claim_too(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    _pending_sor(db_session, project, opening_number="A01", quantity=4)

    assert _row(db_session, project)["claimed_quantity"] == 4


def test_a_live_pull_is_a_claim(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.IN_PROGRESS,
        lines=[("A01", 4)],
    )

    row = _row(db_session, project)
    assert (row["sent_quantity"], row["claimed_quantity"], row["suggested_quantity"]) == (0, 4, 2)


def test_an_accepted_request_is_counted_once_through_its_pull(db_session):
    """The double-count case. Accept copies the request's lines onto a pull, so a term that read
    both would charge the opening 8 for a request that asked for 4."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 10)
    req = _pending_sar(db_session, project, opening_number="A01", quantity=4)
    pull = _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        lines=[("A01", 4)],
    )
    req.status = ShopAssemblyRequestStatus.APPROVED
    req.pull_request_id = pull.id
    db_session.flush()

    row = _row(db_session, project)
    assert row["claimed_quantity"] == 4
    assert row["suggested_quantity"] == 6


def test_a_completed_pull_leaves_claimed_and_enters_sent_in_one_step(db_session):
    """The other half of the same invariant: it must never be in both terms at once, and must never
    fall out of both."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 10)
    req = _pending_sar(db_session, project, opening_number="A01", quantity=4)
    pull = _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        lines=[("A01", 4)],
    )
    req.status = ShopAssemblyRequestStatus.APPROVED
    req.pull_request_id = pull.id
    db_session.flush()

    pull.status = PullRequestStatus.COMPLETED
    db_session.flush()

    row = _row(db_session, project)
    assert (row["sent_quantity"], row["claimed_quantity"]) == (4, 0)
    assert row["suggested_quantity"] == 6


def test_a_rejected_request_claims_nothing(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    req = _pending_sar(db_session, project, opening_number="A01", quantity=4)
    req.status = ShopAssemblyRequestStatus.REJECTED
    db_session.flush()

    assert _row(db_session, project)["claimed_quantity"] == 0


def test_a_soft_deleted_pull_claims_nothing(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 6)
    pull = _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.IN_PROGRESS,
        lines=[("A01", 4)],
    )
    pull.deleted_at = datetime.utcnow()
    db_session.flush()

    assert _row(db_session, project)["claimed_quantity"] == 0


# --- the floor ----------------------------------------------------------------------------------


def test_a_lowered_schedule_reads_zero_rather_than_negative(db_session):
    """A re-upload that drops what an opening is owed below what has already gone out. Nothing is
    auto-unwound: a human decides what to do about hardware already at site."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 2)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 5)],
    )

    row = _row(db_session, project)
    assert row["owed_quantity"] == 2
    assert row["sent_quantity"] == 5
    assert row["suggested_quantity"] == 0


def test_a_product_the_schedule_no_longer_lists_still_gets_a_row(db_session):
    """Dropping it would make a lowered schedule look like nothing ever happened, which is the one
    case where a silent zero is worse than a visible one."""
    project = _project(db_session)
    _opening(db_session, project)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 3)],
    )

    row = _row(db_session, project)
    assert row is not None
    assert (row["owed_quantity"], row["sent_quantity"], row["suggested_quantity"]) == (0, 3, 0)


def test_an_opening_the_schedule_dropped_entirely_still_reports_what_it_was_sent(db_session):
    """The opening row is gone, so `owed` cannot resolve - but the tag on the pull line survives,
    and pretending the departure never happened would re-offer it."""
    project = _project(db_session)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        lines=[("GONE-1", 3)],
    )

    rows = request_composer.get_request_coverage(db_session, project.id, ["GONE-1"])
    assert [(r["opening_number"], r["owed_quantity"], r["sent_quantity"]) for r in rows] == [("GONE-1", 0, 3)]


# --- scoping ------------------------------------------------------------------------------------


def test_another_openings_departure_does_not_count_against_this_one(db_session):
    project = _project(db_session)
    a01 = _opening(db_session, project, "A01")
    a02 = _opening(db_session, project, "A02")
    _owe(db_session, project, a01, 5)
    _owe(db_session, project, a02, 5)
    _pull(
        db_session,
        project,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        lines=[("A02", 5)],
    )

    rows = request_composer.get_request_coverage(db_session, project.id, ["A01", "A02"])
    by_opening = {r["opening_number"]: r for r in rows}
    assert by_opening["A01"]["suggested_quantity"] == 5
    assert by_opening["A02"]["suggested_quantity"] == 0


def test_another_projects_departure_does_not_count_against_this_one(db_session):
    project = _project(db_session)
    other = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 5)
    _pull(
        db_session,
        other,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", 5)],
    )

    assert _row(db_session, project)["suggested_quantity"] == 5


# --- on order -----------------------------------------------------------------------------------


def test_on_order_counts_placed_pos_and_nets_off_what_arrived(db_session):
    """Not an allocation to this opening - it answers "is more coming, or is this all there will
    ever be"."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 5)

    po = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=f"PO-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=POStatus.PARTIALLY_RECEIVED,
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=CAT,
            product_code=CODE,
            ordered_quantity=10,
            received_quantity=4,
        )
    )
    db_session.flush()

    assert _row(db_session, project)["on_order_quantity"] == 6


def test_a_draft_po_is_not_on_order(db_session):
    """Nobody has ordered it, so promising it to a requester would be a lie."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 5)

    po = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=f"PO-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=POStatus.DRAFT,
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=CAT,
            product_code=CODE,
            ordered_quantity=10,
            received_quantity=0,
        )
    )
    db_session.flush()

    assert _row(db_session, project)["on_order_quantity"] == 0


def test_availability_is_deliberately_absent(db_session):
    """`projectInventoryAvailability` is the single answer to "what may I claim" (#342), and the
    creation gate is applied against that number. A second figure computed here at a slightly
    different instant is exactly the drift that would let the panel say 3 and the gate say 2."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 5)

    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(db_session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=CAT,
        product_code=CODE,
        quantity=99,
        deficient_quantity=0,
    )
    db_session.add(si)
    db_session.flush()
    db_session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=si.id,
            warehouse_id=warehouse_id,
            hardware_category=CAT,
            product_code=CODE,
            quantity=99,
            deficient_quantity=0,
        )
    )
    db_session.flush()

    row = _row(db_session, project)
    assert not any("available" in key for key in row)
    assert row["suggested_quantity"] == 5


def test_the_read_is_a_fixed_number_of_statements_however_many_openings(db_session):
    """The perf contract (CLAUDE.md): eight statements whether the composer is asked about one
    opening or two hundred. A per-opening query here is the N+1 that turns "fast on dev" into a
    frozen page."""
    project = _project(db_session)
    for index in range(40):
        opening = _opening(db_session, project, f"A{index:03d}")
        _owe(db_session, project, opening, 2)
    db_session.flush()

    statements: list[str] = []
    from sqlalchemy import event

    def record(conn, cursor, statement, parameters, context, executemany):
        statements.append(statement)

    event.listen(db_session.get_bind(), "before_cursor_execute", record)
    try:
        rows = request_composer.get_request_coverage(db_session, project.id, [f"A{index:03d}" for index in range(40)])
    finally:
        event.remove(db_session.get_bind(), "before_cursor_execute", record)

    assert len(rows) == 40
    assert len(statements) == 8, statements


def test_openings_asked_for_twice_are_answered_once(db_session):
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 3)

    rows = request_composer.get_request_coverage(db_session, project.id, ["A01", "A01"])
    assert len(rows) == 1


def test_the_composer_reads_the_schedule_that_is_there_now(db_session):
    """`owed` is the CURRENT schedule, so a re-upload changes the answer without anything else
    moving - which is what makes composing off it safe after a revision."""
    project = _project(db_session)
    opening = _opening(db_session, project)
    _owe(db_session, project, opening, 4)
    assert _row(db_session, project)["owed_quantity"] == 4

    for item in db_session.scalars(select(HardwareItem).where(HardwareItem.opening_id == opening.id)).all():
        db_session.delete(item)
    _owe(db_session, project, opening, 9)

    assert _row(db_session, project)["owed_quantity"] == 9
