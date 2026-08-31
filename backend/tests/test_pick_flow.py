"""User-dictated per-location pull picking (#367).

Approving a pull used to deduct inventory FIFO by `received_at` in the same call, and nothing
recorded where the hardware physically came from - the warehouse user, the only person who can see
the racks, never chose. The deduction moves to an explicit pick confirmation: the picker names a
quantity per location, and confirming that is what moves stock.

What these tests pin, in order: starting a pick moves nothing; a draft is a note and replaces
wholesale; a confirmation deducts the exact rows named and consumes the claim behind them; neither
a row nor a product code can be over-pulled; a short confirm is a resumable state that keeps the
un-picked remainder claimed; completion is refused until the pick is confirmed; and a cancel puts
the hardware back on the rows it came off.

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime, timedelta

import pytest
from sqlalchemy import func, select

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AuditAction,
    NotificationType,
    PullPickLineState,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
)
from app.models.inventory import InventoryLocation
from app.models.notification import Notification
from app.models.project import Project
from app.models.pull_pick_line import PullPickLine
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository
from tests.pick_helpers import pick_pull

HINGE = ("HINGE", "HG-100")


# --- fixtures ----------------------------------------------------------------------------------


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(
    session,
    project_id,
    *,
    category=HINGE[0],
    code=HINGE[1],
    quantity,
    deficient=0,
    aisle="A",
    row="1",
    bay="1",
    received_at=None,
) -> InventoryLocation:
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    when = received_at or datetime.utcnow()
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=deficient,
        received_at=when,
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
        aisle=aisle,
        row=row,
        bay=bay,
        received_at=when,
    )
    session.add(il)
    session.flush()
    return il


def _pending_pull(session, project_id, *, needs, source=PullRequestSource.SHOP_ASSEMBLY) -> PullRequest:
    """A PENDING pull with one line per (category, code, qty, opening) in `needs`."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project_id,
        source=source,
        status=PullRequestStatus.PENDING,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    for category, code, qty, opening in needs:
        session.add(
            PullRequestItem(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                opening_number=opening,
                hardware_category=category,
                product_code=code,
                requested_quantity=qty,
            )
        )
    session.flush()
    return pr


def _started_pull(session, project_id, *, needs, by="picker") -> PullRequest:
    pr = _pending_pull(session, project_id, needs=needs)
    warehouse_repository.start_pull_request_pick(session, pr.id, by)
    session.flush()
    return pr


def _line(row: InventoryLocation, quantity: int) -> warehouse_repository.PickLine:
    return warehouse_repository.PickLine(
        hardware_category=row.hardware_category,
        product_code=row.product_code,
        inventory_location_id=row.id,
        quantity=quantity,
    )


def _pick_lines(session, pr_id, state=None):
    stmt = select(PullPickLine).where(PullPickLine.pull_request_id == pr_id)
    if state is not None:
        stmt = stmt.where(PullPickLine.state == state)
    return list(session.scalars(stmt).all())


def _audits(session, action, entity_id=None):
    stmt = select(InventoryAuditLog).where(InventoryAuditLog.action == action)
    if entity_id is not None:
        stmt = stmt.where(InventoryAuditLog.entity_id == entity_id)
    return list(session.scalars(stmt).all())


def _two_opening_request(session, project, *, qty=2, code=HINGE[1]):
    """A shop-assembly request over two openings, through the real creation path."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {
                    "opening_number": opening_number,
                    "hardware_category": HINGE[0],
                    "product_code": code,
                    "quantity": qty,
                }
                for opening_number in ("A01", "A02")
            ],
        },
    )


def _accepted_pull(session, project, *, qty=2):
    """Create the request and accept it. Returns (sar, pr) with the pull still PENDING."""
    sar = _two_opening_request(session, project, qty=qty)["shop_assembly_request"]
    shop_assembly_repository.accept_shop_assembly_request(session, sar.id, "acceptor")
    session.flush()
    pr = session.scalar(select(PullRequest).where(PullRequest.request_number == sar.request_number))
    return sar, pr


# --- starting the pick -------------------------------------------------------------------------


def test_starting_a_pick_moves_nothing(db_session):
    """The whole point of splitting approve in two: opening a pull for picking is not a stock write."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=10)
    pr = _pending_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()

    assert pr.status == PullRequestStatus.IN_PROGRESS
    assert pr.assigned_to == "picker"
    assert pr.approved_at is not None
    assert pr.picked_at is None
    assert row.quantity == 10
    assert _audits(db_session, AuditAction.PULL_DEDUCTION) == []


def test_starting_a_pick_does_not_gate_on_availability(db_session):
    """The old approve refused a pull it could not fill, before anybody had looked at a rack. Now
    scarcity is discovered where it is visible, and a pull with nothing on the shelf still opens."""
    project = _make_project(db_session)
    pr = _pending_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()

    assert pr.status == PullRequestStatus.IN_PROGRESS


def test_a_pull_can_only_be_started_once(db_session):
    project = _make_project(db_session)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 1, "A01")])

    with pytest.raises(InvalidStateTransitionError):
        warehouse_repository.start_pull_request_pick(db_session, pr.id, "someone-else")


# --- the sheet ---------------------------------------------------------------------------------


def test_the_sheet_groups_by_product_and_lists_every_opening(db_session):
    """No truncation anywhere: the picker builds carts door by door, so the opening list is the
    work."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    pr = _started_pull(
        db_session,
        project.id,
        needs=[(*HINGE, 2, "A01"), (*HINGE, 3, "A02"), ("CLOSER", "CL-1", 1, "A01")],
    )

    sheet = warehouse_repository.get_pick_sheet(db_session, pr.id)

    hinge = next(s for s in sheet.sections if s.product_code == HINGE[1])
    assert hinge.required_quantity == 5
    assert hinge.applied_quantity == 0
    assert hinge.remaining_quantity == 5
    assert [(o.opening_number, o.quantity) for o in hinge.openings] == [("A01", 2), ("A02", 3)]
    # A combo with no inventory row still gets a section - that is how the picker finds out.
    closer = next(s for s in sheet.sections if s.product_code == "CL-1")
    assert closer.locations == []


def test_the_sheet_shows_every_location_oldest_first_with_no_suggestion(db_session):
    project = _make_project(db_session)
    older = _seed_inventory(db_session, project.id, quantity=2, aisle="A", received_at=datetime(2020, 1, 1))
    newer = _seed_inventory(db_session, project.id, quantity=5, aisle="B", received_at=datetime(2024, 1, 1))
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 3, "A01")])

    section = warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0]

    assert [loc.inventory_location_id for loc in section.locations] == [older.id, newer.id]
    assert [loc.available for loc in section.locations] == [2, 5]
    # Received dates are carried so the picker can rotate stock themselves. Nothing on this type
    # proposes a quantity - the only numbers are what is there and what has already been taken.
    assert [loc.received_at.year for loc in section.locations] == [2020, 2024]
    assert [loc.draft_quantity for loc in section.locations] == [0, 0]


def test_a_row_picked_to_zero_stays_on_the_sheet(db_session):
    """Otherwise the row a picker took twelve hinges off vanishes the moment they confirm, and the
    screen stops matching the paper in their hand."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=2)
    _seed_inventory(db_session, project.id, quantity=5, aisle="B")
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 2)], "picker")
    db_session.flush()

    section = warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0]
    drained = next(loc for loc in section.locations if loc.inventory_location_id == row.id)
    assert (drained.available, drained.applied_quantity) == (0, 2)


def test_deficient_units_are_not_offered(db_session):
    """A condemned unit is back in the building but is not pickable, the same rule the deduction
    applies."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5, deficient=3)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 5, "A01")])

    section = warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0]

    assert [loc.available for loc in section.locations] == [2]


# --- the draft ---------------------------------------------------------------------------------


def test_a_draft_moves_nothing_and_survives_a_reload(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=10)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    warehouse_repository.save_pick_draft(db_session, pr.id, [_line(row, 3)], "picker")
    db_session.flush()

    assert row.quantity == 10
    assert pr.picked_at is None
    section = warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0]
    assert section.locations[0].draft_quantity == 3


def test_saving_a_draft_replaces_the_whole_sheet(db_session):
    """Replace-all, not merge: a save says "this is the sheet now", and a crossed-out row has to go."""
    project = _make_project(db_session)
    first = _seed_inventory(db_session, project.id, quantity=10, aisle="A")
    second = _seed_inventory(db_session, project.id, quantity=10, aisle="B")
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 6, "A01")])

    warehouse_repository.save_pick_draft(db_session, pr.id, [_line(first, 3), _line(second, 3)], "picker")
    db_session.flush()
    warehouse_repository.save_pick_draft(db_session, pr.id, [_line(second, 5)], "picker")
    db_session.flush()

    drafts = _pick_lines(db_session, pr.id, PullPickLineState.DRAFT)
    assert [(d.inventory_location_id, d.quantity) for d in drafts] == [(second.id, 5)]


def test_a_draft_may_exceed_what_is_available(db_session):
    """A draft is a note, not a claim. Blocking a picker from writing down what is on their sheet
    while the numbers are mid-entry would make the save button useless exactly when it is wanted -
    `confirm_pick` is the gate."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=2)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 9, "A01")])

    warehouse_repository.save_pick_draft(db_session, pr.id, [_line(row, 9)], "picker")
    db_session.flush()

    assert row.quantity == 2


def test_a_draft_is_refused_for_a_combo_that_is_not_on_the_pull(db_session):
    project = _make_project(db_session)
    other = _seed_inventory(db_session, project.id, category="CLOSER", code="CL-1", quantity=5)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    with pytest.raises(ValidationError):
        warehouse_repository.save_pick_draft(db_session, pr.id, [_line(other, 1)], "picker")


def test_a_draft_is_refused_for_another_projects_stock(db_session):
    project = _make_project(db_session)
    elsewhere = _make_project(db_session)
    foreign = _seed_inventory(db_session, elsewhere.id, quantity=5)
    _seed_inventory(db_session, project.id, quantity=5)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    with pytest.raises(ValidationError):
        warehouse_repository.save_pick_draft(db_session, pr.id, [_line(foreign, 1)], "picker")


# --- confirming --------------------------------------------------------------------------------


def test_confirming_deducts_exactly_the_rows_dictated(db_session):
    """The point of the whole slice: the picker chooses, including against FIFO order."""
    project = _make_project(db_session)
    older = _seed_inventory(db_session, project.id, quantity=5, aisle="A", received_at=datetime(2020, 1, 1))
    newer = _seed_inventory(db_session, project.id, quantity=5, aisle="B", received_at=datetime(2024, 1, 1))
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    # Deliberately against the old FIFO order: 1 off the old row, 3 off the new one.
    result = warehouse_repository.confirm_pick(db_session, pr.id, [_line(older, 1), _line(newer, 3)], "picker")
    db_session.flush()

    assert result.outcome == "PICKED"
    assert result.applied_quantity == 4
    assert (older.quantity, newer.quantity) == (4, 2)
    assert pr.picked_at is not None
    assert pr.picked_by == "picker"


def test_confirming_writes_one_applied_line_and_one_audit_per_row(db_session):
    project = _make_project(db_session)
    first = _seed_inventory(db_session, project.id, quantity=5, aisle="A")
    second = _seed_inventory(db_session, project.id, quantity=5, aisle="B")
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    warehouse_repository.confirm_pick(db_session, pr.id, [_line(first, 1), _line(second, 3)], "picker")
    db_session.flush()

    applied = sorted(_pick_lines(db_session, pr.id, PullPickLineState.APPLIED), key=lambda pl: pl.quantity)
    assert [(pl.inventory_location_id, pl.quantity) for pl in applied] == [(first.id, 1), (second.id, 3)]
    assert all(pl.applied_at is not None and pl.entered_by == "picker" for pl in applied)

    audits = _audits(db_session, AuditAction.PULL_DEDUCTION, entity_id=second.id)
    assert len(audits) == 1
    detail = audits[0].detail
    assert (detail["deducted"], detail["oldQuantity"], detail["newQuantity"]) == (3, 5, 2)
    # Location detail is on the audit row, which is what makes the deduction reconstructable.
    assert (detail["aisle"], detail["row"], detail["bay"]) == ("B", "1", "1")
    assert detail["warehouseCode"]


def test_confirming_discards_the_draft(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=5)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    warehouse_repository.save_pick_draft(db_session, pr.id, [_line(row, 2)], "picker")
    db_session.flush()
    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 2)], "picker")
    db_session.flush()

    assert _pick_lines(db_session, pr.id, PullPickLineState.DRAFT) == []


def test_a_row_cannot_give_up_more_than_it_has(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=2)
    _seed_inventory(db_session, project.id, quantity=5, aisle="B")
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    with pytest.raises(ValidationError, match="only 2 available"):
        warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 3)], "picker")


def test_two_lines_on_one_row_are_checked_as_one_withdrawal(db_session):
    """Two leaves picked off the same bin is one thing as far as the shelf is concerned."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=3)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01"), (*HINGE, 2, "A02")])

    with pytest.raises(ValidationError):
        warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 2), _line(row, 2)], "picker")


def test_a_pull_never_takes_more_than_it_asked_for(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=50)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    with pytest.raises(ValidationError, match="more than the 4"):
        warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 5)], "picker")


def test_the_over_pull_ceiling_counts_what_is_already_picked(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=50)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 3)], "picker")
    db_session.flush()

    with pytest.raises(ValidationError, match="3 already picked"):
        warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 2)], "picker")


def test_contention_is_only_blamed_when_it_is_the_whole_obstacle(db_session):
    """A shortfall can be part claim and part plain scarcity. Telling a picker "the units are on the
    shelf but they are spoken for" when half of them do not exist anywhere sends them after a
    competing request that cannot explain the gap - so the message is reserved for the case where
    removing the claim would have let the entry through."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=5)
    # A live claim on 4 of the 5, held by somebody else.
    sar, _other = _accepted_pull(db_session, project, qty=2)
    assert warehouse_repository.get_reserved_total(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 4
    stranger = _started_pull(db_session, project.id, needs=[(*HINGE, 10, "A01")])

    # 10 wanted, 5 on hand: reservations are not what stops this, scarcity is.
    with pytest.raises(ValidationError, match="only 5 available"):
        warehouse_repository.confirm_pick(db_session, stranger.id, [_line(row, 10)], "picker")

    # 3 wanted, 5 on hand, 4 claimed: now the claim genuinely is the only obstacle.
    with pytest.raises(ConflictError, match="already claimed this stock"):
        warehouse_repository.confirm_pick(db_session, stranger.id, [_line(row, 3)], "picker")

    assert row.quantity == 5


def test_a_pull_cannot_pick_past_what_other_requests_have_left_free(db_session):
    """The third ceiling. The units are on the shelf and reachable; they are somebody else's."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=10)
    # A live claim on 8 of the 10, held by a request that is not this pull.
    sar, _other_pull = _accepted_pull(db_session, project, qty=4)  # reserves 8 across two leaves
    assert warehouse_repository.get_reserved_total(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 8

    stranger = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    with pytest.raises(ConflictError, match="already claimed this stock"):
        warehouse_repository.confirm_pick(db_session, stranger.id, [_line(row, 4)], "picker")

    assert row.quantity == 10


def test_confirming_with_nothing_entered_is_refused_while_stock_is_there(db_session):
    """A no-op submission with the hardware sitting on the shelf. It would deduct nothing, report
    the whole requirement short, and raise a PO backfill signal for a walk nobody took - and then
    dedupe would let that suppress the real signal from the pick that followed."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=5)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    with pytest.raises(ValidationError, match="Nothing was entered"):
        warehouse_repository.confirm_pick(db_session, pr.id, [], "picker")

    assert (
        db_session.scalar(select(func.count()).select_from(Notification).where(Notification.pull_request_id == pr.id))
        == 0
    )


def test_confirming_with_nothing_entered_is_allowed_when_there_was_nothing_to_pick(db_session):
    """The other reading of an empty sheet, and the one that must keep working: the picker walked
    the racks and the bin was empty. That is a real outcome - the direct analogue of the old
    approve-time INSUFFICIENT - so it confirms short of everything and purchasing is told."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=0)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    result = warehouse_repository.confirm_pick(db_session, pr.id, [], "picker")
    db_session.flush()

    assert result.outcome == "SHORT"
    assert result.applied_quantity == 0
    assert pr.picked_at is None
    assert [(s.product_code, s.short) for s in result.shortfalls] == [(HINGE[1], 4)]
    assert result.notification is not None


def test_a_soft_deleted_pull_cannot_be_started(db_session):
    """`lock_rows` does not filter soft-deletes. Without the check the status flip commits and the
    resolver's re-read then fails, leaving the pull IN_PROGRESS and unpickable forever."""
    project = _make_project(db_session)
    pr = _pending_pull(db_session, project.id, needs=[(*HINGE, 1, "A01")])
    pr.deleted_at = datetime.utcnow()
    db_session.flush()

    with pytest.raises(NotFoundError):
        warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")

    assert pr.status == PullRequestStatus.PENDING


def test_a_plain_shortage_is_not_reported_as_contention(db_session):
    """The combo ceiling runs before the row one, so it sees a plain over-entry first. It must not
    describe that as another request's claim - there is no competing request to go and find, and the
    useful answer is which bin came up short."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=3)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    with pytest.raises(ValidationError, match="only 3 available"):
        warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 4)], "picker")

    assert row.quantity == 3


def test_the_sheet_says_how_much_is_claimable_before_the_walk(db_session):
    """A blocking gate the picker only meets after walking the racks is a trap. The number that
    decides the refusal is on the sheet, so contention is visible up front."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    sar, _other_pull = _accepted_pull(db_session, project, qty=4)  # claims 8
    assert warehouse_repository.get_reserved_total(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 8
    stranger = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    section = warehouse_repository.get_pick_sheet(db_session, stranger.id).sections[0]

    # Ten on the shelf, eight spoken for: two are claimable against the four this pull needs.
    assert sum(loc.available for loc in section.locations) == 10
    assert section.claimable_quantity == 2
    assert section.claimable_shortfall == 2


def test_claimable_quantity_is_the_whole_shelf_when_nothing_competes(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=6)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 4, "A01")])

    section = warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0]

    assert (section.claimable_quantity, section.claimable_shortfall) == (6, 0)


def test_a_confirmed_pick_cannot_be_confirmed_again(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=5)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])
    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 2)], "picker")
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError, match="already been picked"):
        warehouse_repository.confirm_pick(db_session, pr.id, [], "picker")


def test_a_pull_cannot_be_picked_before_it_is_started(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=5)
    pr = _pending_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    with pytest.raises(InvalidStateTransitionError, match="Start the pick first"):
        warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 2)], "picker")


# --- the short path ----------------------------------------------------------------------------


def test_a_short_confirm_deducts_what_was_entered_and_stays_open(db_session):
    """Refusing the whole confirmation would mean a picker who found nine of twelve hinges has to
    put the nine back. Nobody does that; they mark the pull complete anyway and the system lies."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=9)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 12, "A01")])

    result = warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 9)], "picker")
    db_session.flush()

    assert result.outcome == "SHORT"
    assert result.applied_quantity == 9
    assert row.quantity == 0
    assert pr.status == PullRequestStatus.IN_PROGRESS
    assert pr.picked_at is None
    assert [(s.product_code, s.requested, s.short) for s in result.shortfalls] == [(HINGE[1], 12, 3)]


def test_a_short_confirm_notification_speaks_the_pick_frame(db_session):
    """A pick shortfall's numbers are (requested, free-now, still-owed). The creation-gate template
    rendered them as "need 12, N available (short 3)" - arithmetic that only holds in the gate frame
    where short = need - available - so purchasing read a contradiction."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=9)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 12, "A01")])

    result = warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 9)], "picker")
    db_session.flush()

    assert result.notification is not None
    assert f"{HINGE[0]} {HINGE[1]}: 9 of 12 picked - 3 still owed (0 free in the project now)" in (
        result.notification.message
    )


def test_a_short_confirm_notifies_purchasing_once_per_pull(db_session):
    """A picker keying a big sheet in three sittings must not raise three identical backfill signals
    for the same gap."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=9)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 12, "A01")])

    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 5)], "picker")
    db_session.flush()
    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 4)], "picker")
    db_session.flush()

    notifs = list(
        db_session.scalars(
            select(Notification).where(
                Notification.pull_request_id == pr.id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
            )
        ).all()
    )
    assert len(notifs) == 1


def test_a_second_confirm_covers_the_remainder_and_stamps_picked(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=9)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 12, "A01")])

    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 9)], "picker")
    db_session.flush()
    # The backfill lands.
    later = _seed_inventory(db_session, project.id, quantity=3, aisle="C")
    result = warehouse_repository.confirm_pick(db_session, pr.id, [_line(later, 3)], "picker")
    db_session.flush()

    assert result.outcome == "PICKED"
    assert pr.picked_at is not None
    assert sum(pl.quantity for pl in _pick_lines(db_session, pr.id, PullPickLineState.APPLIED)) == 12


def test_a_short_confirm_keeps_the_un_picked_part_of_the_claim(db_session):
    """Consumption is per combo and partial. The remainder is still owed to this request, so handing
    it to whoever asks next is the exact hole #342 closed."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=4)
    sar, pr = _accepted_pull(db_session, project, qty=2)  # two leaves x 2 = 4 claimed

    il.quantity = 3  # an admin override under the live claim
    db_session.flush()

    result = pick_pull(db_session, pr.id, "picker")

    assert result.outcome == "SHORT"
    assert warehouse_repository.get_reserved_total(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 1


def test_a_short_confirm_on_a_reserved_pull_records_an_integrity_event(db_session):
    """The reserved path is not supposed to be able to come up short, so when it does the discrepancy
    stays investigable rather than reading like the ordinary PR-REPL shortfall."""
    project = _make_project(db_session)
    il = _seed_inventory(db_session, project.id, quantity=4)
    _sar, pr = _accepted_pull(db_session, project, qty=2)

    il.quantity = 3
    db_session.flush()
    pick_pull(db_session, pr.id, "picker")

    integrity = [
        row
        for row in _audits(db_session, AuditAction.PULL_DEDUCTION, entity_id=pr.id)
        if (row.detail or {}).get("integrityError") == "RESERVED_PULL_SHORT"
    ]
    assert len(integrity) == 1


# --- what the pick gates -----------------------------------------------------------------------


def test_completion_is_refused_until_the_pick_is_confirmed(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    with pytest.raises(InvalidStateTransitionError, match="not been picked yet"):
        warehouse_repository.complete_pull_request(db_session, pr.id, "picker")


def test_cancelling_returns_the_units_to_the_exact_rows_they_came_off(db_session):
    """The old per-combo inverse landed everything on the newest row, because the FIFO deduction kept
    no record of where it took from. A dictated pick does, so a bin that gave up twelve hinges gets
    twelve hinges back - which is what makes a physical recount agree with the system."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)  # so the accept's reservation fits
    _sar, pr = _accepted_pull(db_session, project, qty=2)
    older = db_session.scalar(select(InventoryLocation).where(InventoryLocation.project_id == project.id))
    newer = _seed_inventory(db_session, project.id, quantity=10, aisle="B", received_at=datetime(2030, 1, 1))
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()
    warehouse_repository.confirm_pick(db_session, pr.id, [_line(older, 1), _line(newer, 3)], "picker")
    db_session.flush()
    assert (older.quantity, newer.quantity) == (19, 7)

    warehouse_repository.cancel_pull_request(db_session, pr.id, "manager", "wrong project")
    db_session.flush()

    assert (older.quantity, newer.quantity) == (20, 10)
    restock_audits = _audits(db_session, AuditAction.PULL_RESTOCK, entity_id=newer.id)
    assert len(restock_audits) == 1
    assert restock_audits[0].detail["returnedToSourceRow"] is True


def test_cancelling_before_the_pick_restocks_nothing(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr = _accepted_pull(db_session, project, qty=2)
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    warehouse_repository.save_pick_draft(db_session, pr.id, [_line(row, 4)], "picker")
    db_session.flush()

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "manager")
    db_session.flush()

    assert result.restocked == []
    assert row.quantity == 20
    # A draft is a note about hardware, not a hold on it - it dies with the pull.
    assert _pick_lines(db_session, pr.id) == []


def test_cancelling_an_un_picked_pull_leaves_the_request_holding_one_claim(db_session):
    """The claim is consumed at the pick now, so a pull cancelled before its pick still holds all of
    it. Re-creating the request's full need on top of that would double-claim the same units."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=20)
    sar, pr = _accepted_pull(db_session, project, qty=2)
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()

    warehouse_repository.cancel_pull_request(db_session, pr.id, "manager")
    db_session.flush()

    assert warehouse_repository.get_reserved_total(db_session, ReservationSource.SHOP_ASSEMBLY_REQUEST, sar.id) == 4


def test_cancelling_a_short_picked_pull_returns_only_what_was_picked(db_session):
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr = _accepted_pull(db_session, project, qty=2)
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()
    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 1)], "picker")
    db_session.flush()
    assert row.quantity == 19

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "manager")
    db_session.flush()

    assert [(r.product_code, r.quantity) for r in result.restocked] == [(HINGE[1], 1)]
    assert row.quantity == 20


def test_a_deleted_source_row_falls_back_to_the_per_combo_return(db_session):
    """ON DELETE SET NULL degrades the pick line to "these units came from somewhere that no longer
    exists", which the restock reads as "fall back to the project's newest row"."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr = _accepted_pull(db_session, project, qty=2)
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    db_session.flush()
    warehouse_repository.confirm_pick(db_session, pr.id, [_line(row, 4)], "picker")
    db_session.flush()
    # The location goes away, exactly as a merge or an admin delete would leave it.
    for line in _pick_lines(db_session, pr.id, PullPickLineState.APPLIED):
        line.inventory_location_id = None
    db_session.flush()

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "manager")
    db_session.flush()

    assert [(r.product_code, r.quantity) for r in result.restocked] == [(HINGE[1], 4)]
    assert row.quantity == 20  # the newest (only) row for the combo
    assert any(a.detail.get("returnedToSourceRow") is False for a in _audits(db_session, AuditAction.PULL_RESTOCK))


def test_a_legacy_pull_still_restocks_per_combo(db_session):
    """The migration's backfill population: picked under the old model, so there are no pick lines to
    reverse row by row and the per-combo return is the only honest answer."""
    project = _make_project(db_session)
    row = _seed_inventory(db_session, project.id, quantity=20)
    _sar, pr = _accepted_pull(db_session, project, qty=2)
    warehouse_repository.start_pull_request_pick(db_session, pr.id, "picker")
    # Hand-simulate the old approve: deduct, stamp picked, write no pick lines.
    row.quantity -= 4
    pr.picked_at = pr.approved_at
    pr.picked_by = "picker"
    db_session.flush()

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "manager")
    db_session.flush()

    assert [(r.product_code, r.quantity) for r in result.restocked] == [(HINGE[1], 4)]
    assert row.quantity == 20


def test_discarding_a_pending_pull_takes_its_pick_lines_with_it(db_session):
    project = _make_project(db_session)
    pr = _pending_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    warehouse_repository.discard_pending_pull_request(db_session, pr.id)
    db_session.flush()

    assert db_session.get(PullRequest, pr.id) is None
    assert _pick_lines(db_session, pr.id) == []


def test_a_missing_pull_is_a_not_found(db_session):
    with pytest.raises(NotFoundError):
        warehouse_repository.get_pick_sheet(db_session, uuid.uuid4())


def test_the_sheet_orders_sections_and_openings_predictably(db_session):
    """Two pickers looking at the same pull see the same sheet in the same order - the paper and the
    screen have to be walkable together."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10)
    _seed_inventory(db_session, project.id, category="CLOSER", code="CL-1", quantity=10)
    pr = _started_pull(
        db_session,
        project.id,
        needs=[(*HINGE, 1, "A02"), ("CLOSER", "CL-1", 1, "A01"), (*HINGE, 1, "A01")],
    )

    sheet = warehouse_repository.get_pick_sheet(db_session, pr.id)

    assert [s.product_code for s in sheet.sections] == ["CL-1", HINGE[1]]
    hinge = sheet.sections[1]
    assert [o.opening_number for o in hinge.openings] == ["A01", "A02"]


def test_received_at_is_the_only_rotation_signal_on_the_sheet(db_session):
    """A regression pin for the decision that shaped this whole screen: no suggested split, no
    suggested column, no autofill. If a `suggested_*` attribute ever appears on these types, the
    system has started deciding again."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, quantity=10, received_at=datetime.utcnow() - timedelta(days=30))
    pr = _started_pull(db_session, project.id, needs=[(*HINGE, 2, "A01")])

    location = warehouse_repository.get_pick_sheet(db_session, pr.id).sections[0].locations[0]

    assert not [name for name in vars(location) if "suggest" in name.lower()]
    assert location.received_at is not None
