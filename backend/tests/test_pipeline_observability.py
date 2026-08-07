"""Pipeline observability and the notifications that go with it (#344).

Three things are pinned here.

**The pipeline is correct.** A multi-opening request is walked the whole way - requested, accepted,
part-staged, assigned, half-built, finished, shipped - and the derived stage and every count is
asserted at each step, including the states slices 1-5 introduced (the #342 integrity note, units
awaiting replacement, a replacement that arrived after its leaf shipped, and a cancelled pull).

**The pipeline is flat.** `get_assembly_pipeline_summaries` issues a fixed number of statements
whether it covers one request or many, and `get_assembly_pipeline` a fixed number whether the request
has two openings or thirty. That is the property that makes the All-Projects view survivable, and it
is the one an innocent-looking refactor would break, so it is asserted rather than described.

**The notifications fire once.** Staging announces one signal per confirmation and not per opening;
completing a pull that staging already finished says nothing; a replacement arriving reaches the
assembler holding the leaf, or shipping if the leaf has gone; and the unblocked-replacement signal
dedupes to one open notification per pull.

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import event, select

from app.models.enums import (
    AssemblyStatus,
    NotificationType,
    OpeningItemState,
    POStatus,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    PullStatus,
    ShopAssemblyRequestStatus,
)
from app.models.inventory import InventoryLocation
from app.models.notification import Notification
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository
from app.schemas.enums import PickOutcome, PipelineStage
from tests.pick_helpers import mark_picked, pick_pull

# --- helpers -----------------------------------------------------------------------------------


class _StatementCounter:
    """Counts SQL statements issued on the test session's connection.

    The point of the pipeline resolvers is that their statement count does not move with the size of
    the result, so the tests below assert an exact number rather than "not too many": an exact number
    fails loudly the first time somebody adds a per-row lookup, which is precisely the regression
    CLAUDE.md's perf rules are about.
    """

    def __init__(self, session):
        self._bind = session.get_bind()
        self.statements: list[str] = []

    def __enter__(self):
        event.listen(self._bind, "before_cursor_execute", self._record)
        return self

    def __exit__(self, *_exc):
        event.remove(self._bind, "before_cursor_execute", self._record)
        return False

    def _record(self, _conn, _cursor, statement, _params, _context, _executemany):
        self.statements.append(statement)

    @property
    def count(self) -> int:
        return len(self.statements)


def _make_project(session, description="Test") -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description=description)
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category="HINGE", code="HG-100", quantity, deficient=0):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
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
        deficient_quantity=deficient,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _request(session, project, *, leaves=(1, 2), qty=2, code="HG-100", opening_number="A01"):
    """A shop-assembly request over N leaves of one opening, through the real creation path."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening_number}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": opening_number,
                    "leaf": leaf,
                    "items": [{"hardware_category": "HINGE", "product_code": code, "quantity": qty}],
                }
                for leaf in leaves
            ],
        },
    )["shop_assembly_request"]


def _accept(session, sar) -> PullRequest:
    shop_assembly_repository.accept_shop_assembly_request(session, sar.id, "acceptor")
    session.flush()
    return session.scalar(
        select(PullRequest).where(
            PullRequest.request_number == sar.request_number,
            PullRequest.status != PullRequestStatus.CANCELLED,
        )
    )


def _openings(session, pr) -> list[ShopAssemblyOpening]:
    return list(
        session.scalars(
            select(ShopAssemblyOpening)
            .where(ShopAssemblyOpening.pull_request_id == pr.id)
            .order_by(ShopAssemblyOpening.leaf.asc())
        ).all()
    )


def _summary(session, sar):
    rows = shop_assembly_repository.get_assembly_pipeline_summaries(session, request_ids=[sar.id])
    assert len(rows) == 1
    return rows[0]


def _notifications(session, notification_type):
    return list(session.scalars(select(Notification).where(Notification.type == notification_type)).all())


def _make_po_with_line(session, project_id, *, code="HG-100", category="HINGE", ordered=10):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
    )
    session.add(po)
    session.flush()
    li = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category=category,
        product_code=code,
        ordered_quantity=ordered,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
        gp_line_ord=1,
    )
    session.add(li)
    session.flush()
    return po, li


def _receive(session, po, li, quantity):
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
    )


# --- the ladder --------------------------------------------------------------------------------


def test_pipeline_walks_a_request_from_requested_to_shipped(db_session):
    """The whole journey, one rung at a time, on a two-leaf request.

    Each assertion is the answer to "where is opening A01 leaf 2?" at that moment, and the request's
    own stage is always the *least* advanced of its openings - what is holding it up, not its best
    news. That is the reading the detail header and the list row both use.
    """
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project)

    # 1. Requested: no pull exists yet, nothing is staged.
    s = _summary(db_session, sar)
    assert s.stage == "REQUESTED"
    assert (s.opening_count, s.staged_opening_count, s.planned_unit_count) == (2, 0, 4)
    assert s.pull_request_id is None
    assert s.staging_status == PullStatus.NOT_PULLED
    assert [o.stage for o in shop_assembly_repository.get_assembly_pipeline(db_session, sar.id).openings] == [
        "REQUESTED",
        "REQUESTED",
    ]

    # 2. Accepted: the pull is minted but not approved, so nothing has left inventory.
    pr = _accept(db_session, sar)
    s = _summary(db_session, sar)
    assert s.stage == "ACCEPTED"
    assert s.pull_request_id == pr.id
    assert s.pull_request_status == PullRequestStatus.PENDING
    assert s.accepted_by == "acceptor"

    # 3. Approved but unstaged: stock is deducted, no cart is built.
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    openings = _openings(db_session, pr)
    assert _summary(db_session, sar).stage == "PULLING"

    # 4. One cart staged: that leaf is workable, the other is not - so the request still reads
    #    PULLING, and the staging rollup derives PARTIAL.
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    s = _summary(db_session, sar)
    assert (s.stage, s.staging_status, s.staged_opening_count) == ("PULLING", PullStatus.PARTIAL, 1)
    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    assert [o.stage for o in detail.openings] == ["STAGED", "PULLING"]
    assert detail.openings[0].staged_by == "picker"

    # 5. Both staged: the pull completes, both leaves are on the board unassigned.
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[1].id], "picker")
    db_session.flush()
    s = _summary(db_session, sar)
    assert (s.stage, s.staging_status, s.staged_opening_count) == ("STAGED", PullStatus.PULLED, 2)
    assert s.pull_request_status == PullRequestStatus.COMPLETED

    # 6. One claimed: the request is still waiting on the unclaimed one.
    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user_1", "Ana")
    db_session.flush()
    s = _summary(db_session, sar)
    assert (s.stage, s.assigned_opening_count) == ("STAGED", 1)
    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    assert [o.stage for o in detail.openings] == ["ASSIGNED", "STAGED"]
    assert detail.openings[0].assigned_to == "Ana"

    shop_assembly_repository.assign_openings(db_session, [openings[1].id], "user_2", "Bo")
    db_session.flush()
    assert _summary(db_session, sar).stage == "ASSIGNED"

    # 7. Work starts on leaf 1: n/m units is the reading, not "some progress".
    items = list(
        db_session.scalars(
            select(ShopAssemblyOpeningItem).where(ShopAssemblyOpeningItem.shop_assembly_opening_id == openings[0].id)
        ).all()
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        openings[0].id,
        [shop_assembly_repository.AssemblyProgressUpdate(items[0].id, installed_quantity=1)],
        performed_by="Ana",
    )
    db_session.flush()
    s = _summary(db_session, sar)
    # The request is held back by leaf 2, which nobody has touched.
    assert (s.stage, s.in_progress_opening_count, s.installed_unit_count) == ("ASSIGNED", 1, 1)
    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    assert [o.stage for o in detail.openings] == ["IN_PROGRESS", "ASSIGNED"]
    assert (detail.openings[0].installed_unit_count, detail.openings[0].planned_unit_count) == (1, 2)

    # 8. Leaf 1 finished: an OpeningItem exists and the pipeline reports where it was put away.
    shop_assembly_repository.record_assembly_progress(
        db_session,
        openings[0].id,
        [shop_assembly_repository.AssemblyProgressUpdate(items[0].id, installed_quantity=2)],
        performed_by="Ana",
    )
    db_session.flush()
    leaf_one = shop_assembly_repository.complete_opening(db_session, openings[0].id, completed_by="Ana")
    db_session.flush()
    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    assert detail.openings[0].stage == "COMPLETED"
    # #498: completion no longer places the leaf, so the pipeline shows it unlocated until the
    # warehouse assigns a warehouse and bin from the put-away queue.
    assert detail.openings[0].assembled_location is None
    assert detail.openings[0].opening_item_id == leaf_one.id
    assert _summary(db_session, sar).completed_opening_count == 1

    # 9. Leaf 1 ships: the rung above COMPLETED, and the one the shipping module writes.
    leaf_one.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()
    s = _summary(db_session, sar)
    assert s.shipped_opening_count == 1
    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    assert detail.openings[0].stage == "SHIPPED"
    # And the request still reads by its slowest leaf, which is still on the bench.
    assert s.stage == "ASSIGNED"


def test_request_stage_is_always_the_minimum_of_its_opening_stages(db_session):
    """The list row and the detail header are computed two different ways - the row from grouped
    aggregates, the leaves from their own columns - so this pins them together.

    They have to be two implementations: deriving the request stage from loaded opening rows would
    make the All-Projects list load every opening in the system. This test is what stops them
    drifting apart.
    """
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    sar = _request(db_session, project, leaves=(1, 2))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    openings = _openings(db_session, pr)

    def _check():
        detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
        expected = min(
            (o.stage for o in detail.openings),
            key=lambda s: shop_assembly_repository.PIPELINE_STAGE_RANK[s],
        )
        assert detail.summary.stage == expected

    _check()
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    _check()
    shop_assembly_repository.assign_openings(db_session, [openings[0].id], "user_1", "Ana")
    db_session.flush()
    _check()
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[1].id], "picker")
    db_session.flush()
    _check()
    shop_assembly_repository.assign_openings(db_session, [openings[1].id], "user_2", "Bo")
    db_session.flush()
    _check()


def test_unassigning_an_in_progress_leaf_still_reads_in_progress(db_session):
    """`remove_opening_from_user` (#340) allows unassigning a half-built leaf, so "assigned" and
    "started" are independent facts. The aggregate stage derivation has to hold up under that, which
    is why it counts staged-and-untouched openings separately rather than subtracting."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project, leaves=(1,))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    opening = _openings(db_session, pr)[0]
    warehouse_repository.stage_pull_openings(db_session, pr.id, [opening.id], "picker")
    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_1", "Ana")
    db_session.flush()
    item = db_session.scalar(
        select(ShopAssemblyOpeningItem).where(ShopAssemblyOpeningItem.shop_assembly_opening_id == opening.id)
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [shop_assembly_repository.AssemblyProgressUpdate(item.id, installed_quantity=1)],
        performed_by="Ana",
    )
    shop_assembly_repository.remove_opening_from_user(db_session, opening.id)
    db_session.flush()

    s = _summary(db_session, sar)
    assert (s.stage, s.assigned_opening_count, s.in_progress_opening_count) == ("IN_PROGRESS", 0, 1)


def test_rejected_request_reads_rejected_whatever_its_openings_say(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project)
    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "acceptor", "wrong project")
    db_session.flush()

    s = _summary(db_session, sar)
    assert s.stage == "REJECTED"
    assert s.rejected_by == "acceptor"
    assert all(
        o.stage == "REJECTED" for o in shop_assembly_repository.get_assembly_pipeline(db_session, sar.id).openings
    )


def test_cancelled_pull_shows_as_cancelled_with_its_history(db_session):
    """A cancellation (#343) restocks, detaches the openings and returns the request to PENDING - so
    without the cancelled pull in view, the request would read as though it had never been accepted
    at all. That is exactly the confusion this view exists to remove."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project)
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    warehouse_repository.cancel_pull_request(db_session, pr.id, "supervisor", "raised on the wrong project")
    db_session.flush()

    s = _summary(db_session, sar)
    assert s.stage == "CANCELLED"
    assert s.request_status == ShopAssemblyRequestStatus.PENDING
    assert s.cancelled_pull_count == 1
    assert s.last_cancelled_by == "supervisor"
    assert s.last_cancellation_reason == "raised on the wrong project"
    # The live pull is gone, not merely cancelled: the request is claimable again.
    assert s.pull_request_id is None
    assert all(
        o.stage == "CANCELLED" for o in shop_assembly_repository.get_assembly_pipeline(db_session, sar.id).openings
    )


def test_re_accepting_after_a_cancel_shows_the_live_pull_and_keeps_the_history(db_session):
    """#343 made request_number unique only among live pulls, so a re-accept legitimately mints a
    second pull with the same number. The pipeline must resolve the live one and still count the
    cancelled one."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project)
    first = _accept(db_session, sar)
    pick_pull(db_session, first.id, "picker")
    db_session.flush()
    warehouse_repository.cancel_pull_request(db_session, first.id, "supervisor", None)
    db_session.flush()
    second = _accept(db_session, sar)
    db_session.flush()

    s = _summary(db_session, sar)
    assert s.pull_request_id == second.id
    assert s.pull_request_status == PullRequestStatus.PENDING
    assert s.cancelled_pull_count == 1
    assert s.stage == "ACCEPTED"


def test_pipeline_surfaces_the_integrity_note(db_session):
    """The #342 flag the accept screen already shows. Carried here too, so the pipeline does not
    quietly become a second, more trusting view of the same request."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project)
    sar.integrity_note = "A schedule re-upload landed under this request."
    db_session.flush()

    assert _summary(db_session, sar).integrity_note == "A schedule re-upload landed under this request."


def test_awaiting_replacement_and_arrived_after_ship_are_both_visible(db_session):
    """The two replacement flags (#341), which is where they finally meet the eye.

    A leaf is finished with one unit condemned, its replacement arrives after the leaf has shipped,
    and the pipeline reports both that the leaf is still owed a unit and that the unit that turned up
    cannot be fitted to it.
    """
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project, leaves=(1,), qty=2)
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    opening = _openings(db_session, pr)[0]
    warehouse_repository.stage_pull_openings(db_session, pr.id, [opening.id], "picker")
    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_1", "Ana")
    db_session.flush()
    item = db_session.scalar(
        select(ShopAssemblyOpeningItem).where(ShopAssemblyOpeningItem.shop_assembly_opening_id == opening.id)
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            shop_assembly_repository.AssemblyProgressUpdate(
                item.id, installed_quantity=1, flag_deficient_quantity=1, deficient_reason="bent"
            )
        ],
        performed_by="Ana",
    )
    db_session.flush()

    # Owed one unit while still on the bench.
    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    assert detail.openings[0].awaiting_replacement_unit_count == 1
    assert detail.openings[0].replacement_arrived_after_ship is False
    assert _summary(db_session, sar).awaiting_replacement_opening_count == 1

    # Finish and ship the leaf, then let the replacement land.
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [shop_assembly_repository.AssemblyProgressUpdate(item.id, installed_quantity=1)],
        performed_by="Ana",
    )
    db_session.flush()
    leaf = shop_assembly_repository.complete_opening(db_session, opening.id, completed_by="Ana")
    leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    repl = db_session.scalar(select(PullRequest).where(PullRequest.request_number == f"PR-REPL-{pr.request_number}"))
    mark_picked(db_session, repl)
    warehouse_repository.complete_pull_request(db_session, repl.id, completed_by="picker")
    db_session.flush()

    detail = shop_assembly_repository.get_assembly_pipeline(db_session, sar.id)
    row = detail.openings[0]
    assert row.stage == "SHIPPED"
    assert row.replacement_pending_unit_count == 1
    assert row.awaiting_replacement_unit_count == 1
    assert row.replacement_arrived_after_ship is True
    s = _summary(db_session, sar)
    assert s.replacement_after_ship_opening_count == 1
    assert s.replacement_pending_unit_count == 1


def test_summaries_scope_by_project_and_status(db_session):
    project_a = _make_project(db_session, "A")
    project_b = _make_project(db_session, "B")
    _seed_inventory(db_session, project_a.id, quantity=20)
    _seed_inventory(db_session, project_b.id, quantity=20)
    sar_a = _request(db_session, project_a, leaves=(1,))
    sar_b = _request(db_session, project_b, leaves=(1,))
    _accept(db_session, sar_a)

    scoped = shop_assembly_repository.get_assembly_pipeline_summaries(db_session, project_id=project_b.id)
    assert [r.request_id for r in scoped] == [sar_b.id]
    assert (scoped[0].project_name, scoped[0].project_code) == ("B", project_b.project_id)

    pending = shop_assembly_repository.get_assembly_pipeline_summaries(
        db_session, status=ShopAssemblyRequestStatus.APPROVED
    )
    assert sar_a.id in {r.request_id for r in pending}
    assert sar_b.id not in {r.request_id for r in pending}


# --- flatness ----------------------------------------------------------------------------------


def test_pipeline_detail_query_count_is_flat_as_openings_grow(db_session):
    """Eight statements for two openings, eight for thirty.

    The detail view loads its opening rows in one statement and aggregates their hardware lines in
    another, so an N+1 here would be a per-opening `find_assembled_leaf` or a lazy `items` walk -
    both of which are exactly what a well-meaning edit reaches for. Comparing two request sizes,
    rather than asserting a bare number, is what makes the failure message say *what* went wrong.
    """
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=400)
    small = _request(db_session, project, leaves=(1, 2), opening_number="A01")
    big_leaves = tuple(range(1, 31))
    # 30 leaves of one opening: a pair in the schedule is two, but the query shape is what is under
    # test, and this is the cheapest way to make the row count move by an order of magnitude.
    big = _request(db_session, project, leaves=big_leaves, opening_number="B01")

    with _StatementCounter(db_session) as small_counter:
        small_detail = shop_assembly_repository.get_assembly_pipeline(db_session, small.id)
    with _StatementCounter(db_session) as big_counter:
        big_detail = shop_assembly_repository.get_assembly_pipeline(db_session, big.id)

    assert len(small_detail.openings) == 2
    assert len(big_detail.openings) == 30
    assert big_counter.count == small_counter.count, (
        f"statement count moved with opening count: {small_counter.count} for 2 openings, "
        f"{big_counter.count} for 30.\n" + "\n".join(big_counter.statements)
    )
    assert big_counter.count == 8


def test_pipeline_summaries_query_count_is_flat_as_requests_grow(db_session):
    """Five statements for one request, five for twelve - the All-Projects guarantee.

    This is the resolver that runs with no project filter, so a per-request follow-up query here
    would be a query per shop-assembly request that has ever existed.
    """
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=400)
    first = _request(db_session, project, leaves=(1,), opening_number="C01")

    with _StatementCounter(db_session) as one_counter:
        one = shop_assembly_repository.get_assembly_pipeline_summaries(db_session, project_id=project.id)
    assert [r.request_id for r in one] == [first.id]

    for n in range(2, 13):
        _request(db_session, project, leaves=(1, 2), opening_number=f"C{n:02d}")

    with _StatementCounter(db_session) as many_counter:
        many = shop_assembly_repository.get_assembly_pipeline_summaries(db_session, project_id=project.id)
    assert len(many) == 12

    assert many_counter.count == one_counter.count, (
        f"statement count moved with request count: {one_counter.count} for 1 request, "
        f"{many_counter.count} for 12.\n" + "\n".join(many_counter.statements)
    )
    assert many_counter.count == 5


# --- notifications -----------------------------------------------------------------------------


def test_staging_notifies_the_manager_audience_once_per_confirmation(db_session):
    """One signal per trip to the shelf, not one per cart. A bell that fires per opening on a
    forty-opening pull is a bell nobody reads."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    sar = _request(db_session, project, leaves=(1, 2, 3))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    openings = _openings(db_session, pr)

    warehouse_repository.stage_pull_openings(db_session, pr.id, [o.id for o in openings[:2]], "picker")
    db_session.flush()

    notes = _notifications(db_session, NotificationType.ASSEMBLY_WORK_AVAILABLE)
    assert len(notes) == 1
    from app.services import notification_service

    assert notes[0].recipient_role == notification_service.SHOP_ASSEMBLY_MANAGER_RECIPIENT_ROLE
    assert notes[0].pull_request_id == pr.id
    assert "2 opening(s)" in notes[0].message
    assert "still being picked" in notes[0].message


def test_staging_the_last_opening_announces_once_not_twice(db_session):
    """Staging the last cart calls `complete_pull_request`, which also flips openings to PULLED. The
    two must not both announce - and they cannot, because each announces only the openings *it*
    made workable, and by then there are none left for completion to flip."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    sar = _request(db_session, project, leaves=(1, 2))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    openings = _openings(db_session, pr)

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[1].id], "picker")
    db_session.flush()

    notes = _notifications(db_session, NotificationType.ASSEMBLY_WORK_AVAILABLE)
    assert len(notes) == 2
    assert "That was the last of the pull." in notes[-1].message


def test_re_staging_an_already_staged_opening_announces_nothing(db_session):
    """A double-click is a no-op in #343, and it has to be a no-op in the bell too."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    sar = _request(db_session, project, leaves=(1, 2))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    openings = _openings(db_session, pr)

    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()

    assert len(_notifications(db_session, NotificationType.ASSEMBLY_WORK_AVAILABLE)) == 1


def test_completing_an_unstaged_pull_directly_still_announces(db_session):
    """`complete_pull_request` called on its own means "stage whatever is left". Those openings do
    become workable, so that call is the one that has to speak."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    sar = _request(db_session, project, leaves=(1, 2))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()

    warehouse_repository.complete_pull_request(db_session, pr.id, completed_by="picker")
    db_session.flush()

    notes = _notifications(db_session, NotificationType.ASSEMBLY_WORK_AVAILABLE)
    assert len(notes) == 1
    assert "2 opening(s)" in notes[0].message
    assert "That was the last of the pull." in notes[0].message


def _leaf_with_deficiency(db_session, project, *, complete=False, assign_to=("user_1", "Ana")):
    """One leaf with a unit condemned at the bench, so a PR-REPL pull exists for it."""
    sar = _request(db_session, project, leaves=(1,), qty=2)
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    opening = _openings(db_session, pr)[0]
    warehouse_repository.stage_pull_openings(db_session, pr.id, [opening.id], "picker")
    shop_assembly_repository.assign_openings(db_session, [opening.id], assign_to[0], assign_to[1])
    db_session.flush()
    item = db_session.scalar(
        select(ShopAssemblyOpeningItem).where(ShopAssemblyOpeningItem.shop_assembly_opening_id == opening.id)
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [
            shop_assembly_repository.AssemblyProgressUpdate(
                item.id, installed_quantity=1, flag_deficient_quantity=1, deficient_reason="bent"
            )
        ],
        performed_by=assign_to[1],
    )
    db_session.flush()
    if complete:
        shop_assembly_repository.record_assembly_progress(
            db_session,
            opening.id,
            [shop_assembly_repository.AssemblyProgressUpdate(item.id, installed_quantity=1)],
            performed_by=assign_to[1],
        )
        db_session.flush()
        shop_assembly_repository.complete_opening(db_session, opening.id, completed_by=assign_to[1])
        db_session.flush()
    repl = db_session.scalar(select(PullRequest).where(PullRequest.request_number == f"PR-REPL-{pr.request_number}"))
    return sar, pr, opening, item, repl


def test_replacement_arrival_notifies_the_leafs_assignee(db_session):
    """The half of the #341 loop that was silent: the arrival that the assembler can actually act
    on. Addressed to their stable Clerk user id, which is the assignment the opening already holds."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, _pr, _opening, _item, repl = _leaf_with_deficiency(db_session, project)

    mark_picked(db_session, repl)
    warehouse_repository.complete_pull_request(db_session, repl.id, completed_by="picker")
    db_session.flush()

    notes = _notifications(db_session, NotificationType.REPLACEMENT_ARRIVED)
    assert len(notes) == 1
    assert notes[0].recipient_role == "user_1"
    assert notes[0].pull_request_id == repl.id
    assert "remaining work" in notes[0].message
    # The shipped-leaf signal is somebody else's problem and must not also fire.
    assert _notifications(db_session, NotificationType.REPLACEMENT_AFTER_SHIPMENT) == []


def test_replacement_arrival_on_a_shipped_leaf_notifies_shipping_and_not_the_assembler(db_session):
    """Once the leaf has left the building, fitting it is not the assembler's job - it is
    reallocation's. Exactly one of the two signals fires, and it is the other one."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar, _pr, opening, _item, repl = _leaf_with_deficiency(db_session, project, complete=True)
    leaf = shop_assembly_repository.find_assembled_leaf(db_session, project.id, opening.opening_id, opening.leaf)
    leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    mark_picked(db_session, repl)
    warehouse_repository.complete_pull_request(db_session, repl.id, completed_by="picker")
    db_session.flush()

    assert len(_notifications(db_session, NotificationType.REPLACEMENT_AFTER_SHIPMENT)) == 1
    assert _notifications(db_session, NotificationType.REPLACEMENT_ARRIVED) == []
    assert _summary(db_session, sar).replacement_after_ship_opening_count == 1


def test_replacement_arrival_on_an_unassigned_leaf_notifies_nobody(db_session):
    """A notification with no addressee is noise. An unassigned leaf's replacement is picked up by
    whoever claims the work."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    _sar, _pr, opening, _item, repl = _leaf_with_deficiency(db_session, project)
    shop_assembly_repository.remove_opening_from_user(db_session, opening.id)
    db_session.flush()

    mark_picked(db_session, repl)
    warehouse_repository.complete_pull_request(db_session, repl.id, completed_by="picker")
    db_session.flush()

    assert _notifications(db_session, NotificationType.REPLACEMENT_ARRIVED) == []


# --- the unblocked-pull loop and its dedupe -----------------------------------------------------


def _blocked_replacement_pull(db_session, project, *, need=3, code="HG-900"):
    """A PENDING PR-REPL pull for a combo the project has none of."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-REPL-SA-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.PENDING,
        requested_by="Ana",
    )
    db_session.add(pr)
    db_session.flush()
    # sa_opening_item_id is what makes it structurally a replacement pull, so it needs a real one.
    sar = _request(db_session, project, leaves=(1,), qty=1, code="HG-100", opening_number=f"Z{uuid.uuid4().hex[:3]}")
    sa_item = db_session.scalar(
        select(ShopAssemblyOpeningItem)
        .join(ShopAssemblyOpening, ShopAssemblyOpening.id == ShopAssemblyOpeningItem.shop_assembly_opening_id)
        .where(ShopAssemblyOpening.shop_assembly_request_id == sar.id)
    )
    db_session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            item_type=PullRequestItemType.LOOSE,
            opening_number="Z01",
            leaf=1,
            sa_opening_item_id=sa_item.id,
            hardware_category="HINGE",
            product_code=code,
            requested_quantity=need,
        )
    )
    db_session.flush()
    return pr


def test_receiving_unblocks_a_replacement_pull_and_notifies_the_warehouse(db_session):
    """The backfill retry loop. A replacement pull holds no reservation by design (#342), so nothing
    else was going to notice that the stock it was waiting on had turned up."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    repl = _blocked_replacement_pull(db_session, project, need=3)
    po, li = _make_po_with_line(db_session, project.id, code="HG-900")

    _receive(db_session, po, li, 3)
    db_session.flush()

    notes = _notifications(db_session, NotificationType.PULL_UNBLOCKED)
    assert len(notes) == 1
    from app.services import notification_service

    assert notes[0].recipient_role == notification_service.WAREHOUSE_RECIPIENT_ROLE
    assert notes[0].pull_request_id == repl.id
    assert repl.request_number in notes[0].message


def test_a_receive_that_does_not_close_the_gap_says_nothing(db_session):
    """Transition, not proximity: the signal means "you can approve this now". Narrowing a shortfall
    is not something the warehouse can act on, so announcing it would be telling somebody to go and
    fail."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    _blocked_replacement_pull(db_session, project, need=3)
    po, li = _make_po_with_line(db_session, project.id, code="HG-900")

    _receive(db_session, po, li, 2)
    db_session.flush()

    assert _notifications(db_session, NotificationType.PULL_UNBLOCKED) == []

    # ... and the receive that finally covers it does speak.
    _receive(db_session, po, li, 1)
    db_session.flush()
    assert len(_notifications(db_session, NotificationType.PULL_UNBLOCKED)) == 1


def test_an_unrelated_receive_is_not_even_considered(db_session):
    """A receive of door closers cannot have changed whether a hinge replacement is coverable, so
    the pull is filtered out before any availability arithmetic happens."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    _blocked_replacement_pull(db_session, project, need=1)
    _seed_inventory(db_session, project.id, code="HG-900", quantity=5)
    po, li = _make_po_with_line(db_session, project.id, code="CLOSER-1")

    _receive(db_session, po, li, 5)
    db_session.flush()

    # The pull is fully coverable, but this receive is not what made it so, so it stays quiet.
    assert _notifications(db_session, NotificationType.PULL_UNBLOCKED) == []


def test_the_unblocked_signal_dedupes_to_one_open_notification_per_pull(db_session):
    """One *unread* notification per pull. A replacement can sit PENDING across many receives, and
    re-announcing it every time is how a bell stops being read. Once it has been read, the signal
    has done its job and a later re-coverage is genuinely new information."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    repl = _blocked_replacement_pull(db_session, project, need=3)
    po, li = _make_po_with_line(db_session, project.id, code="HG-900")

    _receive(db_session, po, li, 3)
    db_session.flush()
    assert len(_notifications(db_session, NotificationType.PULL_UNBLOCKED)) == 1

    # A second receive of the same combo: still coverable, still the same open signal.
    _receive(db_session, po, li, 2)
    db_session.flush()
    assert len(_notifications(db_session, NotificationType.PULL_UNBLOCKED)) == 1

    # Somebody reads it, and a later receive is allowed to raise a fresh one.
    for note in _notifications(db_session, NotificationType.PULL_UNBLOCKED):
        note.is_read = True
    db_session.flush()
    _receive(db_session, po, li, 2)
    db_session.flush()
    notes = _notifications(db_session, NotificationType.PULL_UNBLOCKED)
    assert len(notes) == 2
    assert {n.pull_request_id for n in notes} == {repl.id}


def test_an_ordinary_shop_assembly_pull_is_not_treated_as_a_replacement(db_session):
    """The discriminator is structural - a line stamped with `sa_opening_item_id` (#339) - not the
    `PR-REPL-` number prefix. An ordinary accepted pull holds a reservation and is somebody's
    responsibility already; it must not be announced here."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar = _request(db_session, project, leaves=(1,), qty=1)
    _accept(db_session, sar)
    po, li = _make_po_with_line(db_session, project.id, code="HG-100")

    _receive(db_session, po, li, 5)
    db_session.flush()

    assert _notifications(db_session, NotificationType.PULL_UNBLOCKED) == []


def test_a_stock_pool_receive_never_unblocks_a_project_replacement(db_session):
    """A project-less PO routes into the stock pool, which is not project inventory. Allocating from
    the pool to a project is a separate deliberate act, and that is where the signal would belong."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    _blocked_replacement_pull(db_session, project, need=3)
    po, li = _make_po_with_line(db_session, None, code="HG-900")

    _receive(db_session, po, li, 5)
    db_session.flush()

    assert _notifications(db_session, NotificationType.PULL_UNBLOCKED) == []


# --- dead state --------------------------------------------------------------------------------


def test_pick_outcome_replaced_approve_outcome(db_session):
    """#344 deleted ApproveOutcome.CANCELLED as dead state; #367 retired the whole enum.

    `confirm_pick` returns "PICKED" or "SHORT", and neither maps onto the old pair: INSUFFICIENT
    meant "nothing happened, the pull is blocked and still PENDING", SHORT means "some of it
    happened, the pull is In Progress and holds real deducted stock". Both were GraphQL-only and
    never persisted, so the swap needed no migration - a *cancelled pull* is
    `PullRequestStatus.CANCELLED`, a different enum on a real column, and very much alive."""
    assert {v.name for v in PickOutcome} == {"PICKED", "SHORT"}
    assert PullRequestStatus.CANCELLED.value == "CANCELLED"


def test_pull_status_partial_is_derived_and_never_persisted(db_session):
    """The audit's other finding. `PullStatus.PARTIAL` is reachable - it is what
    `StagingSummary.status` returns and what `PullRequest.stagingStatus` and the pipeline's
    `stagingStatus` surface - but no column ever holds it, so it stays in the enum and no migration
    shrinks the Postgres type."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)
    sar = _request(db_session, project, leaves=(1, 2))
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    openings = _openings(db_session, pr)
    warehouse_repository.stage_pull_openings(db_session, pr.id, [openings[0].id], "picker")
    db_session.flush()

    assert _summary(db_session, sar).staging_status == PullStatus.PARTIAL
    assert (
        db_session.scalar(select(ShopAssemblyOpening).where(ShopAssemblyOpening.pull_status == PullStatus.PARTIAL))
        is None
    )


def test_every_pipeline_stage_the_repository_can_emit_is_a_graphql_enum_value(db_session):
    """The ladder is defined once in the repository as strings and once in the schema as a GraphQL
    enum; the converter maps between them. A stage the repository can produce but the schema cannot
    express would be a 500 on the detail view, so the two are pinned together here."""
    assert {s.value for s in PipelineStage} == set(shop_assembly_repository.PIPELINE_STAGE_RANK)


def test_assembly_status_values_are_all_reachable(db_session):
    """PENDING / IN_PROGRESS / COMPLETED, all three written by real code paths since #340."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar = _request(db_session, project, leaves=(1,), qty=1)
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    opening = _openings(db_session, pr)[0]
    assert opening.assembly_status == AssemblyStatus.PENDING

    warehouse_repository.stage_pull_openings(db_session, pr.id, [opening.id], "picker")
    shop_assembly_repository.assign_openings(db_session, [opening.id], "user_1", "Ana")
    db_session.flush()
    item = db_session.scalar(
        select(ShopAssemblyOpeningItem).where(ShopAssemblyOpeningItem.shop_assembly_opening_id == opening.id)
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [shop_assembly_repository.AssemblyProgressUpdate(item.id, installed_quantity=1)],
        performed_by="Ana",
    )
    db_session.flush()
    assert opening.assembly_status == AssemblyStatus.IN_PROGRESS

    shop_assembly_repository.complete_opening(db_session, opening.id, completed_by="Ana")
    db_session.flush()
    assert opening.assembly_status == AssemblyStatus.COMPLETED


# --- lineage: a re-requested leaf is not the leaf that already shipped (#350 review) -------------


def _build_and_complete(db_session, sar, *, assign_to=("user_1", "Ana")):
    """Walk one single-leaf request all the way to an assembled OpeningItem."""
    pr = _accept(db_session, sar)
    pick_pull(db_session, pr.id, "picker")
    db_session.flush()
    opening = _openings(db_session, pr)[0]
    warehouse_repository.stage_pull_openings(db_session, pr.id, [opening.id], "picker")
    shop_assembly_repository.assign_openings(db_session, [opening.id], *assign_to)
    db_session.flush()
    item = db_session.scalar(
        select(ShopAssemblyOpeningItem).where(ShopAssemblyOpeningItem.shop_assembly_opening_id == opening.id)
    )
    shop_assembly_repository.record_assembly_progress(
        db_session,
        opening.id,
        [shop_assembly_repository.AssemblyProgressUpdate(item.id, installed_quantity=item.quantity)],
        performed_by=assign_to[1],
    )
    db_session.flush()
    leaf = shop_assembly_repository.complete_opening(db_session, opening.id, completed_by=assign_to[1])
    db_session.flush()
    return pr, opening, leaf


def test_a_re_requested_leaf_does_not_inherit_the_shipment_of_the_previous_one(db_session):
    """(opening_id, leaf) carries no request lineage, so a leaf that shipped under request 1 matched
    request 2's opening for the same leaf as well. Three things read wrong at once: the new
    request's shipped count, its after-ship count, and the leaf's stage - which jumped straight to
    SHIPPED before anybody had picked its cart."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)

    first = _request(db_session, project, leaves=(1,), qty=2, opening_number="A01")
    _pr1, first_opening, leaf = _build_and_complete(db_session, first)
    leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()
    assert _summary(db_session, first).shipped_opening_count == 1

    # The same physical leaf is sent back to the shop under a brand new request.
    second = _request(db_session, project, leaves=(1,), qty=2, opening_number="A01")
    pr2 = _accept(db_session, second)
    second_opening = _openings(db_session, pr2)[0]
    second_opening.opening_id = first_opening.opening_id
    db_session.flush()

    summary = _summary(db_session, second)
    assert summary.shipped_opening_count == 0
    assert summary.replacement_after_ship_opening_count == 0

    detail = shop_assembly_repository.get_assembly_pipeline(db_session, second.id)
    row = detail.openings[0]
    assert row.stage != PipelineStage.SHIPPED.value
    assert row.opening_item_id is None
    assert row.opening_item_state is None

    # The request that really did ship it still says so.
    assert _summary(db_session, first).shipped_opening_count == 1


def test_the_re_assembled_leaf_reads_as_its_own_unit_in_the_detail(db_session):
    """The other side of the same filter: scoping to COMPLETED openings must not stop a request from
    reading its own leaf - only from reading somebody else's.

    Once *both* requests have finished a unit for the same leaf key, the rollup is deliberately
    conservative (`_shipped_counts` counts an opening as shipped when any of its matched rows
    shipped, and says so). The per-leaf detail is where that ambiguity is resolved properly, live row
    winning, exactly as `find_assembled_leaf` resolves it."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=40)

    first = _request(db_session, project, leaves=(1,), qty=2, opening_number="A01")
    _pr1, first_opening, leaf = _build_and_complete(db_session, first)
    leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()

    second = _request(db_session, project, leaves=(1,), qty=2, opening_number="A01")
    _pr2, second_opening, second_leaf = _build_and_complete(db_session, second)
    second_opening.opening_id = first_opening.opening_id
    second_leaf.opening_id = first_opening.opening_id
    db_session.flush()

    row = shop_assembly_repository.get_assembly_pipeline(db_session, second.id).openings[0]
    assert row.opening_item_id == second_leaf.id
    assert row.opening_item_state == OpeningItemState.IN_INVENTORY
    assert row.stage == PipelineStage.COMPLETED.value

    second_leaf.state = OpeningItemState.SHIPPED_OUT
    db_session.flush()
    assert _summary(db_session, second).shipped_opening_count == 1
    assert shop_assembly_repository.get_assembly_pipeline(db_session, second.id).openings[0].stage == (
        PipelineStage.SHIPPED.value
    )
