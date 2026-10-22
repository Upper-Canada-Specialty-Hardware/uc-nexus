"""Warehouse lists that page and search on the server (#1267, #1268, #1270).

Each list here used to be read in full and narrowed in the browser, or searched with the user's text
as a LIKE pattern. The fixtures stamp explicit timestamps so newest-first order is deterministic, and
every read is narrowed to a project or code made fresh for the test, so rows other tests leave in a
shared database cannot leak into a page.
"""

import uuid
from datetime import date, datetime, timedelta

import pytest

from app.errors import ValidationError
from app.models.enums import POStatus, PullRequestSource, PullRequestStatus, ReceiveDraftStatus
from app.models.project import Project
from app.models.pull_request import PullRequest
from app.models.purchase_order import PurchaseOrder
from app.models.receive_draft import ReceiveDraft
from app.models.receiving import ReceiveRecord
from app.models.stock_item import StockItem
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository

BASE = datetime(2026, 3, 1, 9, 0, 0)


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), company="TUBC", project_id=f"LP-{uuid.uuid4().hex[:8]}", description="paging")
    session.add(p)
    session.flush()
    return p


def _po(session, project, number=None) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company="TUBC",
        po_number=number or f"PO-{uuid.uuid4().hex[:8]}",
        request_number=None,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        gp_company="TUBC",
        vendor_name_snapshot="Acme",
        ordered_at=date.today(),
    )
    session.add(po)
    session.flush()
    return po


def _draft(session, po, status, minutes) -> ReceiveDraft:
    d = ReceiveDraft(
        id=uuid.uuid4(),
        po_id=po.id,
        status=status,
        created_by_user_id="u_1",
        created_by_name="Wendy Warehouse",
        created_at=BASE + timedelta(minutes=minutes),
    )
    session.add(d)
    session.flush()
    return d


def _record(session, po, minutes) -> ReceiveRecord:
    r = ReceiveRecord(id=uuid.uuid4(), po_id=po.id, received_at=BASE + timedelta(minutes=minutes), received_by="r")
    session.add(r)
    session.flush()
    return r


# --- receives (#1267) ---------------------------------------------------------------------------


def test_the_status_filter_reaches_past_the_newest_rows(db_session):
    """A rejected draft older than a page of newer receives is still found: status is filtered in SQL,
    not over a page the browser already cut."""
    project = _project(db_session)
    po = _po(db_session, project)
    old_rejected = _draft(db_session, po, ReceiveDraftStatus.REJECTED, minutes=0)
    for i in range(1, 6):
        _record(db_session, po, minutes=i)

    rows = warehouse_repository.get_all_receives(db_session, limit=3, project_id=project.id, status="REJECTED")

    assert [r["id"] for r in rows] == [old_rejected.id]


def test_approved_means_the_booked_records(db_session):
    project = _project(db_session)
    po = _po(db_session, project)
    _draft(db_session, po, ReceiveDraftStatus.PENDING_APPROVAL, minutes=0)
    record = _record(db_session, po, minutes=1)

    rows = warehouse_repository.get_all_receives(db_session, limit=10, project_id=project.id, status="APPROVED")

    assert [r["id"] for r in rows] == [record.id]


def test_pages_interleave_drafts_and_records_newest_first(db_session):
    """Each side is cut at offset + limit before the merge; the merged pages still come out whole and
    in order, with nothing repeated or skipped."""
    project = _project(db_session)
    po = _po(db_session, project)
    made = []
    for i in range(6):
        if i % 2:
            made.append(_draft(db_session, po, ReceiveDraftStatus.PENDING_APPROVAL, minutes=i).id)
        else:
            made.append(_record(db_session, po, minutes=i).id)
    newest_first = list(reversed(made))

    pages = [
        warehouse_repository.get_all_receives(db_session, limit=2, offset=o, project_id=project.id) for o in (0, 2, 4)
    ]

    assert [r["id"] for page in pages for r in page] == newest_first


def _queued_approval(session, po, outbox_status, minutes) -> ReceiveDraft:
    """A draft approved onto the GP outbox: APPROVED, linked to the row, no receive record yet."""
    from app.repositories import gp_outbox_repository

    draft = _draft(session, po, ReceiveDraftStatus.APPROVED, minutes=minutes)
    row = gp_outbox_repository.enqueue(
        session,
        idempotency_key=f"rcv-{uuid.uuid4().hex}",
        op="create_receive",
        relay_op="create_receipt",
        company="TUBC",
        payload={},
        persist_context={},
        entity_key=f"po:{po.id}",
        label="Receipt",
    )
    row.status = outbox_status
    draft.approved_outbox_entry_id = row.id
    session.flush()
    return draft


@pytest.mark.parametrize(
    ("outbox_status", "state"),
    [
        ("PENDING", "WAITING_ON_GP"),
        ("IN_FLIGHT", "WAITING_ON_GP"),
        ("FAILED", "GP_WRITE_FAILED"),
        ("CANCELLED", "GP_WRITE_FAILED"),
    ],
)
def test_an_approval_still_on_the_outbox_says_what_gp_is_doing(db_session, outbox_status, state):
    """#1947: an approved draft with no record read as plain Approved, as if it were booked, while its
    receipt waited on GP or GP had refused it."""
    project = _project(db_session)
    po = _po(db_session, project)
    queued = _queued_approval(db_session, po, outbox_status, minutes=0)
    pending = _draft(db_session, po, ReceiveDraftStatus.PENDING_APPROVAL, minutes=1)
    record = _record(db_session, po, minutes=2)

    rows = {r["id"]: r for r in warehouse_repository.get_all_receives(db_session, limit=10, project_id=project.id)}

    assert rows[queued.id]["status"] == "APPROVED"
    assert rows[queued.id]["gp_write_state"] == state
    assert rows[pending.id]["gp_write_state"] is None
    assert rows[record.id]["gp_write_state"] is None
    assert all("_outbox_entry_id" not in r for r in rows.values())


def test_the_outbox_rows_for_a_page_are_read_once(db_session):
    """One grouped read for the page, however many queued approvals it holds."""
    from sqlalchemy import event

    project = _project(db_session)
    po = _po(db_session, project)
    for i in range(3):
        _queued_approval(db_session, po, "PENDING", minutes=i)

    outbox_reads: list[str] = []

    def _count(conn, cursor, statement, parameters, context, executemany):
        if "gp_write_outbox" in statement:
            outbox_reads.append(statement)

    engine = db_session.get_bind()
    event.listen(engine, "before_cursor_execute", _count)
    try:
        rows = warehouse_repository.get_all_receives(db_session, limit=10, project_id=project.id)
    finally:
        event.remove(engine, "before_cursor_execute", _count)

    assert [r["gp_write_state"] for r in rows] == ["WAITING_ON_GP"] * 3
    assert len(outbox_reads) == 1


def test_an_unknown_status_is_a_field_error(db_session):
    with pytest.raises(ValidationError) as e:
        warehouse_repository.get_all_receives(db_session, limit=5, status="NOPE")
    assert e.value.field == "status"


def test_the_po_search_treats_wildcards_as_characters(db_session):
    """#1270: `_` in the box is an underscore, not "any character"."""
    project = _project(db_session)
    tag = uuid.uuid4().hex[:6]
    exact = _po(db_session, project, number=f"PO_{tag}")
    lookalike = _po(db_session, project, number=f"POX{tag}")
    _record(db_session, exact, minutes=0)
    _record(db_session, lookalike, minutes=1)

    rows = warehouse_repository.get_all_receives(db_session, limit=10, project_id=project.id, po_search=f"PO_{tag}")

    assert {r["po_id"] for r in rows} == {exact.id}


# --- my drafts (#1889) --------------------------------------------------------------------------


def test_my_drafts_reads_only_the_states_it_shows(db_session):
    """The view shows rejected and waiting drafts; an author's approved ones are left in the database
    rather than read and dropped in the browser."""
    project = _project(db_session)
    po = _po(db_session, project)
    rejected = _draft(db_session, po, ReceiveDraftStatus.REJECTED, minutes=0)
    _draft(db_session, po, ReceiveDraftStatus.APPROVED, minutes=1)
    waiting = _draft(db_session, po, ReceiveDraftStatus.PENDING_APPROVAL, minutes=2)

    rows = warehouse_repository.get_receive_drafts(
        db_session,
        po_id=po.id,
        created_by_user_id="u_1",
        statuses=[ReceiveDraftStatus.REJECTED, ReceiveDraftStatus.PENDING_APPROVAL],
    )

    assert [draft.id for draft, _ in rows] == [waiting.id, rejected.id]


# --- pull history (#1268) -----------------------------------------------------------------------


def _pull(session, project, status, finished_minutes) -> PullRequest:
    at = BASE + timedelta(minutes=finished_minutes)
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=status,
        requested_by="tester",
        created_at=BASE,
        completed_at=at if status == PullRequestStatus.COMPLETED else None,
        cancelled_at=at if status == PullRequestStatus.CANCELLED else None,
    )
    session.add(pr)
    session.flush()
    return pr


def test_pull_history_pages_newest_finished_first(db_session):
    project = _project(db_session)
    made = [
        _pull(
            db_session,
            project,
            PullRequestStatus.CANCELLED if i % 2 else PullRequestStatus.COMPLETED,
            finished_minutes=i,
        ).id
        for i in range(5)
    ]
    newest_first = list(reversed(made))
    terminal = [PullRequestStatus.COMPLETED, PullRequestStatus.CANCELLED]

    pages = [
        warehouse_repository.get_pull_requests(
            db_session, project.id, statuses=terminal, limit=2, offset=o, newest_finished_first=True
        )
        for o in (0, 2, 4)
    ]

    assert [pr.id for page in pages for pr in page] == newest_first


def test_the_unpaged_queue_read_is_unchanged(db_session):
    """No limit keeps the live queue's oldest-first, everything read."""
    project = _project(db_session)
    first = _pull(db_session, project, PullRequestStatus.PENDING, finished_minutes=0)
    first.created_at = BASE
    second = _pull(db_session, project, PullRequestStatus.PENDING, finished_minutes=0)
    second.created_at = BASE + timedelta(minutes=5)
    db_session.flush()

    queue = warehouse_repository.get_pull_requests(db_session, project.id, statuses=[PullRequestStatus.PENDING])

    assert [pr.id for pr in queue] == [first.id, second.id]


# --- stock pool search (#1270) ------------------------------------------------------------------


def test_the_product_code_search_treats_underscore_as_a_character(db_session):
    from app.repositories import warehouse_admin_repository

    wh = warehouse_admin_repository.create_warehouse(
        db_session, name=f"WH {uuid.uuid4().hex[:8]}", code=f"W{uuid.uuid4().hex[:6]}", company="TUBC"
    )
    tag = uuid.uuid4().hex[:6]
    exact = StockItem(
        id=uuid.uuid4(),
        warehouse_id=wh.id,
        hardware_category="HINGE",
        product_code=f"HG_{tag}",
        quantity=1,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    lookalike = StockItem(
        id=uuid.uuid4(),
        warehouse_id=wh.id,
        hardware_category="HINGE",
        product_code=f"HGX{tag}",
        quantity=1,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    db_session.add_all([exact, lookalike])
    db_session.flush()

    found = stock_repository.get_stock_items(db_session, product_code_contains=f"HG_{tag}", warehouse_id=wh.id)

    assert [si.id for si in found] == [exact.id]
