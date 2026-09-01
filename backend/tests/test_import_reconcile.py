"""Reconciliation of a hardware schedule against what the project already has.

The scale tests here exist because of a production outage: reconcile_schedule used to filter its
three bulk queries with `tuple_(opening_number, product_code).in_(pairs)`, and Postgres parses a
row-constructor IN list by recursing once per element. Selecting a whole schedule (thousands of
openings x their hardware) overflowed `max_stack_depth` and the query died with StatementTooComplex.
The wizard swallowed the error, so the Reconciliation step showed an empty grid and the Next button
never enabled - the request flow simply dead-ended with nothing on screen to explain why.

The pairs are matched in Python now. These tests pin both halves of that: the filtering still
excludes exactly what the SQL predicate excluded, and a schedule-sized request completes.
"""

import uuid
from decimal import Decimal

from app.models.enums import (
    HardwareItemState,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import import_repository

CATEGORY = "HINGE"


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _make_opening(session, project, opening_number: str) -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=opening_number)
    session.add(o)
    session.flush()
    return o


def _po_line(session, project, *, status: POStatus, ordered=4, received=0) -> POLineItem:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=status,
        company="TUBC",
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category=CATEGORY,
        product_code="HG-100",
        ordered_quantity=ordered,
        received_quantity=received,
        unit_cost=Decimal("10.00"),
    )
    session.add(line)
    session.flush()
    return line


def _schedule_item(session, project, opening, product_code, quantity, *, line=None) -> HardwareItem:
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=CATEGORY,
        product_code=product_code,
        item_quantity=quantity,
        state=HardwareItemState.IN_PO if line is not None else HardwareItemState.AVAILABLE,
        po_line_item_id=line.id if line is not None else None,
    )
    session.add(hi)
    session.flush()
    return hi


def _request(opening_number, product_code, quantity_needed) -> dict:
    return {
        "opening_number": opening_number,
        "hardware_category": CATEGORY,
        "product_code": product_code,
        "quantity_needed": quantity_needed,
    }


def _by_status(results, opening_number, product_code) -> dict[str, int]:
    return {
        r["status"]: r["quantity"]
        for r in results
        if r["opening_number"] == opening_number and r["product_code"] == product_code
    }


def test_empty_project_reports_the_whole_need_as_a_gap(db_session):
    """The case the user hit: nothing bought yet, so every line is a gap the wizard can carry into POs.

    This is what makes the PO purpose's Next button enable - it auto-selects the NOT_COVERED rows -
    so an empty result here is indistinguishable from a failed query at the UI.
    """
    project = _make_project(db_session)
    _make_opening(db_session, project, "A01")

    results = import_repository.reconcile_schedule(
        db_session, project.id, [_request("A01", "HG-100", 3), _request("A01", "HG-200", 2)]
    )

    assert _by_status(results, "A01", "HG-100") == {"NOT_COVERED": 3}
    assert _by_status(results, "A01", "HG-200") == {"NOT_COVERED": 2}


def test_only_requested_pairs_are_reported(db_session):
    """Dropping the SQL pair predicate must not let off-request rows reach the answer.

    Both decoys sit in the same project, so the project-scoped queries now return them where the old
    predicate filtered them out in the database. A stale opening (A02) and a stale product on a
    requested opening (A01/HG-999) are the two ways a row can be off-request.
    """
    project = _make_project(db_session)
    a01 = _make_opening(db_session, project, "A01")
    a02 = _make_opening(db_session, project, "A02")

    ordered = _po_line(db_session, project, status=POStatus.GP_REGISTERED)
    _schedule_item(db_session, project, a01, "HG-100", 4, line=ordered)
    _schedule_item(db_session, project, a02, "HG-100", 4, line=ordered)
    _schedule_item(db_session, project, a01, "HG-999", 4, line=ordered)

    results = import_repository.reconcile_schedule(db_session, project.id, [_request("A01", "HG-100", 4)])

    assert [(r["opening_number"], r["product_code"]) for r in results] == [("A01", "HG-100")]
    assert _by_status(results, "A01", "HG-100") == {"ORDERED": 4}


def test_buckets_po_lifecycle_and_deducts_open_pulls(db_session):
    """Received stock that an open shop-assembly pull already claims is no longer available.

    Exercises the two data sources the pair filter now guards beyond the PO join - the pull-request
    aggregate query - and pins that a CLOSED PO reads as RECEIVED.
    """
    project = _make_project(db_session)
    a01 = _make_opening(db_session, project, "A01")

    closed = _po_line(db_session, project, status=POStatus.CLOSED, ordered=5, received=5)
    _schedule_item(db_session, project, a01, "HG-100", 5, line=closed)

    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SAR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.IN_PROGRESS,
        requested_by="tester",
    )
    db_session.add(pr)
    db_session.flush()
    db_session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            opening_number="A01",
            hardware_category=CATEGORY,
            product_code="HG-100",
            requested_quantity=2,
        )
    )
    db_session.flush()

    results = import_repository.reconcile_schedule(db_session, project.id, [_request("A01", "HG-100", 5)])

    assert _by_status(results, "A01", "HG-100") == {"RECEIVED": 3, "ASSEMBLING": 2}


def test_handles_a_schedule_sized_request(db_session):
    """2,000 pairs - past the point the old row-constructor IN list blew Postgres' parser stack.

    The user's cliff was around 500 openings of real hardware; this is the same order of magnitude
    with one line per opening, and it has to come back rather than raise StatementTooComplex.
    """
    project = _make_project(db_session)
    _make_opening(db_session, project, "A01")

    items = [_request(f"OP-{i:04d}", "HG-100", 1) for i in range(2000)]
    results = import_repository.reconcile_schedule(db_session, project.id, items)

    assert len(results) == 2000
    assert {r["status"] for r in results} == {"NOT_COVERED"}
