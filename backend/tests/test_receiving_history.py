"""A receive carries the GP receipt it posted, and the history list aggregates them (#447).

Two things are under test and they are two halves of the same feature:

* `create_receive` stores the `receipt_number` / `batch_number` the relay returned, so the Nexus
  receive and the GP receipt share an identifier. Before #447 both were read off the relay response
  and dropped, and reconciling a delivery meant matching PO number and timestamp by hand.
* `get_receiving_history_pos` answers "what did we receive, against what" - the question the other
  receiving lists cannot, because they drop a PO the moment it is complete.

The aggregation assertions are the ones worth keeping honest: the repository computes the totals
with grouped subqueries rather than by walking `po.line_items` / `po.receive_records`, so a
refactor back to the obvious per-row shape has to keep producing these numbers.
"""

import uuid
from datetime import datetime, timedelta
from decimal import Decimal

from app.models.enums import POStatus
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.receiving import ReceiveRecord
from app.repositories import warehouse as warehouse_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_po_with_line(session, project_id, *, status=POStatus.GP_REGISTERED, ordered=10, vendor_name="Acme"):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=status,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        vendor_name_snapshot=vendor_name,
    )
    session.add(po)
    session.flush()
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=ordered,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
        gp_line_ord=1,
    )
    session.add(li)
    session.flush()
    return po, li


def _receive(session, po, li, quantity, *, receipt_number=None, batch_number=None):
    return warehouse_repository.create_receive(
        session,
        po.id,
        "receiver",
        [
            {
                "po_line_item_id": li.id,
                "quantity_received": quantity,
                "locations": [{"aisle": "A", "row": "1", "bay": "1", "quantity": quantity}],
            }
        ],
        receipt_number=receipt_number,
        batch_number=batch_number,
    )


def _row_for(session, po, project_id=None):
    rows = warehouse_repository.get_receiving_history_pos(session, project_id)
    matches = [r for r in rows if r["id"] == po.id]
    return matches[0] if matches else None


# --- the GP receipt on the receive ---------------------------------------------------------------


def test_a_receive_keeps_the_gp_receipt_number_it_posted(db_session):
    """The identifier the warehouse and accounting both call the receipt by. Receiving is GP-first,
    so by the time this row is written GP has already minted it - dropping it was pure loss."""
    project = _make_project(db_session)
    po, li = _make_po_with_line(db_session, project.id)

    rr = _receive(db_session, po, li, 4, receipt_number="RCT0000123", batch_number="EC-2026/07/31")

    assert rr.receipt_number == "RCT0000123"
    assert rr.batch_number == "EC-2026/07/31"


def test_a_receive_without_a_gp_number_is_still_recorded(db_session):
    """Null rather than a refusal. A relay old enough to predate these keys, or a response missing
    them, must not fail a receive against hardware that is physically on the shelf - and the rows
    written before #447 have to stay readable, which is the same nullability."""
    project = _make_project(db_session)
    po, li = _make_po_with_line(db_session, project.id)

    rr = _receive(db_session, po, li, 2)

    assert rr.receipt_number is None
    assert rr.batch_number is None


def test_the_receipt_number_survives_a_reload(db_session):
    """Column, not attribute. The Receiving page reads this back through poReceivingDetails on a
    later request, so an in-memory-only value would look right here and be gone in the app."""
    project = _make_project(db_session)
    po, li = _make_po_with_line(db_session, project.id)
    rr = _receive(db_session, po, li, 3, receipt_number="RCT0000999", batch_number="EC-2026/07/31")
    db_session.flush()
    db_session.expire(rr)

    reloaded = db_session.get(ReceiveRecord, rr.id)

    assert reloaded.receipt_number == "RCT0000999"
    assert reloaded.batch_number == "EC-2026/07/31"


# --- the history aggregation ---------------------------------------------------------------------


def test_two_receives_against_one_po_roll_up_to_one_row(db_session):
    """The counting assertion. Two receives, six of ten units landed, one row - not two, and not a
    row whose totals were summed by iterating the PO's relationship collections."""
    project = _make_project(db_session)
    po, li = _make_po_with_line(db_session, project.id, ordered=10)
    _receive(db_session, po, li, 4, receipt_number="RCT0000001")
    _receive(db_session, po, li, 2, receipt_number="RCT0000002")
    db_session.flush()

    row = _row_for(db_session, po, project.id)

    assert row is not None
    assert row["receive_count"] == 2
    assert row["ordered_total"] == 10
    assert row["received_total"] == 6
    assert row["po_number"] == po.po_number
    assert row["vendor_name"] == "Acme"
    assert row["project_id"] == project.id


def test_last_received_at_is_the_most_recent_receive(db_session):
    """It is a MAX, so back-dating an earlier receive cannot move it. The list sorts on this, and a
    row that reported its first receive would sink a PO that was received yesterday."""
    project = _make_project(db_session)
    po, li = _make_po_with_line(db_session, project.id, ordered=10)
    first = _receive(db_session, po, li, 1)
    second = _receive(db_session, po, li, 1)
    first.received_at = datetime(2026, 1, 1, 9, 0, 0)
    second.received_at = datetime(2026, 6, 1, 9, 0, 0)
    db_session.flush()

    row = _row_for(db_session, po, project.id)

    assert row["last_received_at"] == datetime(2026, 6, 1, 9, 0, 0)


def test_a_po_with_no_receives_is_listed_with_zeroes(db_session):
    """Outer-joined, not inner. A GP-registered PO nobody has touched is exactly what somebody is
    about to receive; dropping it would make the history list say the PO does not exist."""
    project = _make_project(db_session)
    po, _li = _make_po_with_line(db_session, project.id, ordered=7)
    db_session.flush()

    row = _row_for(db_session, po, project.id)

    assert row is not None
    assert row["receive_count"] == 0
    assert row["received_total"] == 0
    assert row["ordered_total"] == 7
    assert row["last_received_at"] is None


def test_a_fully_received_po_stays_in_the_history(db_session):
    """The whole reason this query exists. `create_receive` closes a PO once every line is complete,
    and CLOSED is the status openPOs and backOrderedItems deliberately drop - so reconciliation had
    nowhere to look."""
    project = _make_project(db_session)
    po, li = _make_po_with_line(db_session, project.id, ordered=5)
    _receive(db_session, po, li, 5, receipt_number="RCT0000010")
    db_session.flush()
    assert po.status == POStatus.CLOSED

    row = _row_for(db_session, po, project.id)

    assert row is not None
    assert row["status"] == POStatus.CLOSED
    assert row["received_total"] == 5


def test_a_draft_po_is_not_history(db_session):
    """A PO that never reached GP can have no receipts, so listing it would pad the view with rows
    that can never have anything under them."""
    project = _make_project(db_session)
    po, _li = _make_po_with_line(db_session, project.id, status=POStatus.DRAFT)
    db_session.flush()

    assert _row_for(db_session, po, project.id) is None


def test_a_cancelled_po_is_not_history(db_session):
    project = _make_project(db_session)
    po, _li = _make_po_with_line(db_session, project.id, status=POStatus.CANCELLED)
    db_session.flush()

    assert _row_for(db_session, po, project.id) is None


def test_a_soft_deleted_po_is_not_history(db_session):
    project = _make_project(db_session)
    po, _li = _make_po_with_line(db_session, project.id)
    po.deleted_at = datetime.utcnow() - timedelta(minutes=1)
    db_session.flush()

    assert _row_for(db_session, po, project.id) is None


def test_the_most_recently_received_po_leads_the_list(db_session):
    """The ordering is the whole reading of this list. It answers "what did we receive", so the POs
    with receipts on them come first, newest at the top, and the ones nothing has landed against sink
    to the bottom rather than pushing every actual receipt off the first screen. Somebody about to
    receive is not looking here anyway - the Receive side's own POs Awaiting Receipt table is where
    that PO surfaces."""
    project = _make_project(db_session)
    recent, recent_li = _make_po_with_line(db_session, project.id, ordered=10)
    older, older_li = _make_po_with_line(db_session, project.id, ordered=10)
    never, _ = _make_po_with_line(db_session, project.id, ordered=10)
    _receive(db_session, recent, recent_li, 1).received_at = datetime(2026, 6, 1, 9, 0, 0)
    _receive(db_session, older, older_li, 1).received_at = datetime(2026, 1, 1, 9, 0, 0)
    db_session.flush()

    order = [r["id"] for r in warehouse_repository.get_receiving_history_pos(db_session, project.id)]

    assert order == [recent.id, older.id, never.id]


def test_the_project_filter_narrows_to_that_project(db_session):
    """Cross-project by default - whoever is standing at the dock receives for everyone - with the
    filter for the case where somebody is reconciling one job."""
    a = _make_project(db_session)
    b = _make_project(db_session)
    po_a, _ = _make_po_with_line(db_session, a.id)
    po_b, _ = _make_po_with_line(db_session, b.id)
    db_session.flush()

    assert _row_for(db_session, po_a, a.id) is not None
    assert _row_for(db_session, po_b, a.id) is None
    assert _row_for(db_session, po_b, b.id) is not None
    # No filter: both are visible.
    assert _row_for(db_session, po_a) is not None
    assert _row_for(db_session, po_b) is not None


def test_the_project_filter_still_totals_correctly(db_session):
    """The filter is pushed into the grouped subqueries, not applied only to the outer query, so that
    a one-job page does not group every line item and every receive in the database first. That is an
    optimisation the numbers must survive: the aggregates are computed over a narrowed set of POs, and
    they have to come back identical to what the cross-project call reports for the same PO."""
    a = _make_project(db_session)
    b = _make_project(db_session)
    po_a, li_a = _make_po_with_line(db_session, a.id, ordered=10)
    po_b, li_b = _make_po_with_line(db_session, b.id, ordered=20)
    _receive(db_session, po_a, li_a, 4)
    _receive(db_session, po_a, li_a, 2)
    _receive(db_session, po_b, li_b, 7)
    db_session.flush()

    scoped = _row_for(db_session, po_a, a.id)
    unscoped = _row_for(db_session, po_a)

    assert (scoped["ordered_total"], scoped["received_total"], scoped["receive_count"]) == (10, 6, 2)
    # The other project's receives are not counted in, and dropping them did not lose any of ours.
    assert scoped == unscoped
