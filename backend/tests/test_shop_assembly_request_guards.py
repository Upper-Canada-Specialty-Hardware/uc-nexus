"""A shop-assembly request is held to the schedule (#1133), and its decisions lock it (#1121).

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import update

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import HardwareClassificationChoice, ShopAssemblyOpeningStatus, ShopAssemblyRequestStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.shop_assembly import ShopAssemblyRequest
from app.models.stock_item import StockItem
from app.repositories import (
    classification_override_repository,
    import_repository,
    request_composer,
    shop_assembly_repository,
    warehouse_admin_repository,
)
from app.services import locking
from tests.pick_helpers import pick_pull
from tests.shop_assembly_helpers import batch_lines

_HINGE = {"opening_number": "A01", "hardware_category": "HINGE", "product_code": "HG-100"}


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Guards", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _stock(session, project, quantity=10):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category="HINGE",
        product_code="HG-100",
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=stock.id,
            warehouse_id=warehouse_id,
            hardware_category="HINGE",
            product_code="HG-100",
            quantity=quantity,
            deficient_quantity=0,
            received_at=datetime.utcnow(),
        )
    )
    session.flush()


_SHOP_HINGE = {"hardware_category": "HINGE", "product_code": "HG-100", "unit_cost": 0.0}


def _finalize(session, project, sar_items, *, scheduled=4, classification="SHOP_HARDWARE"):
    """A01 scheduled for `scheduled` HG-100 hinges classified `classification` (None: unclassified),
    and a request raised with `sar_items`."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [{**_HINGE, "item_quantity": scheduled}],
            "classifications": [{**_SHOP_HINGE, "classification": classification}] if classification else [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": sar_items,
        },
    )["shop_assembly_request"]


# --- held to the schedule (#1133) -----------------------------------------------------------------


def test_a_line_within_the_schedule_is_raised(db_session):
    sar = _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 4}])

    assert [(i.opening_number, i.requested_quantity) for i in sar.items] == [("A01", 4)]


def test_a_product_not_on_the_openings_schedule_is_refused(db_session):
    with pytest.raises(ValidationError, match="not on opening A01's schedule") as excinfo:
        _finalize(
            db_session,
            _project(db_session),
            [{"opening_number": "A01", "hardware_category": "CLOSER", "product_code": "CL-1", "quantity": 1}],
        )
    assert excinfo.value.field == "product_code"


def test_a_product_scheduled_on_another_opening_is_refused(db_session):
    """HG-100 is on A01's schedule, not A02's: owing it to A02 is owing an opening hardware it lacks."""
    with pytest.raises(ValidationError, match="not on opening A02's schedule"):
        _finalize(db_session, _project(db_session), [{**_HINGE, "opening_number": "A02", "quantity": 1}])


def test_owing_more_than_the_schedule_gives_is_refused(db_session):
    with pytest.raises(ValidationError, match="gives this opening 4") as excinfo:
        _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 5}])
    assert excinfo.value.field == "requested_quantity"


def test_the_same_line_twice_is_refused(db_session):
    """Batching keys what an opening is owed by (opening, category, code), so a second line for the
    same triple used to replace the first without a word."""
    with pytest.raises(ValidationError, match="appears on the request twice"):
        _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 1}, {**_HINGE, "quantity": 2}])


# --- shop work only (#1425) -----------------------------------------------------------------------


def _schedule_only(session, project, classification="SHOP_HARDWARE"):
    """A01 scheduled for 4 HG-100 hinges, no request - the schedule a composer tab was opened over."""
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [{**_HINGE, "item_quantity": 4}],
            "classifications": [{**_SHOP_HINGE, "classification": classification}],
        },
    )


def _raise_directly(session, project):
    """The request a stale tab sends: straight to the create, with the classification long since moved."""
    return shop_assembly_repository.create_shop_assembly_request(
        session, project.id, [{**_HINGE, "requested_quantity": 4}], created_by="pm"
    )


@pytest.mark.parametrize("classification", ["SITE_HARDWARE", None])
def test_a_product_that_is_not_shop_hardware_is_refused(db_session, classification):
    """Site hardware goes to site loose, and unclassified hardware is not guessed onto a bench - the
    composer offers neither, so the server refuses both."""
    with pytest.raises(ValidationError, match="not shop hardware on this opening") as excinfo:
        _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 4}], classification=classification)
    assert excinfo.value.field == "items"


def test_a_product_moved_to_site_after_the_tab_opened_is_refused(db_session):
    project = _project(db_session)
    _schedule_only(db_session, project)
    classification_override_repository.set_product_classifications(
        db_session, project.id, [("HINGE", "HG-100", HardwareClassificationChoice.UCH_SITE)], changed_by="owner"
    )

    with pytest.raises(ValidationError, match="not shop hardware"):
        _raise_directly(db_session, project)


def test_a_product_marked_by_others_is_refused_whatever_its_rows_say(db_session):
    """By Others leaves the rows' SHOP_HARDWARE in place; the exclusion is what says it is not ours."""
    project = _project(db_session)
    _schedule_only(db_session, project)
    classification_override_repository.set_product_classifications(
        db_session, project.id, [("HINGE", "HG-100", HardwareClassificationChoice.BY_OTHERS)], changed_by="owner"
    )

    with pytest.raises(ValidationError, match="By Others on this project") as excinfo:
        _raise_directly(db_session, project)
    assert excinfo.value.field == "items"


def test_a_finalize_that_makes_the_product_shop_hardware_can_request_it(db_session):
    """An assembly finalize's own classification lands before its request is checked."""
    project = _project(db_session)
    _schedule_only(db_session, project, classification="SITE_HARDWARE")

    sar = _finalize(db_session, project, [{**_HINGE, "quantity": 4}])

    assert [(i.product_code, i.requested_quantity) for i in sar.items] == [("HG-100", 4)]


def test_the_composer_flags_a_by_others_product(db_session):
    """The composer marks what the server would refuse, so the wizard never offers it."""
    project = _project(db_session)
    _schedule_only(db_session, project)
    classification_override_repository.set_product_classifications(
        db_session, project.id, [("HINGE", "HG-100", HardwareClassificationChoice.BY_OTHERS)], changed_by="owner"
    )

    rows = request_composer.get_request_coverage(db_session, project.id, ["A01"])

    assert [(r["product_code"], r["by_others"]) for r in rows] == [("HG-100", True)]


def test_creating_a_request_locks_the_project_before_reading_the_schedule(db_session, monkeypatch):
    """The lock a classification change also takes, so the two cannot interleave."""
    project = _project(db_session)
    _schedule_only(db_session, project)
    statements: list[str] = []
    real_execute = db_session.execute

    def spy(statement, *args, **kwargs):
        try:
            statements.append(str(statement.compile(dialect=db_session.get_bind().dialect)))
        except Exception:  # a text() or other construct with nothing to tell
            statements.append(str(statement))
        return real_execute(statement, *args, **kwargs)

    monkeypatch.setattr(db_session, "execute", spy)
    _raise_directly(db_session, project)

    lock = next(i for i, s in enumerate(statements) if "FOR NO KEY UPDATE" in s and "projects" in s)
    schedule = next(i for i, s in enumerate(statements) if "hardware_items" in s and "sum(" in s)
    assert lock < schedule


# --- decisions lock the request (#1121) -----------------------------------------------------------


@pytest.fixture
def locks_taken(monkeypatch):
    """Every model class lock_rows is asked to lock, in order."""
    seen: list[str] = []
    real = locking.lock_rows

    def spy(session, model_class, ids):
        seen.append(model_class.__name__)
        return real(session, model_class, ids)

    monkeypatch.setattr(locking, "lock_rows", spy)
    return seen


def test_batching_locks_the_request_first(db_session, locks_taken):
    project = _project(db_session)
    _stock(db_session, project)
    sar = _finalize(db_session, project, [{**_HINGE, "quantity": 2}])
    lines = batch_lines(db_session, sar.id)
    locks_taken.clear()

    shop_assembly_repository.create_shop_assembly_batch(db_session, sar.id, lines, created_by="manager")

    assert locks_taken[:1] == ["ShopAssemblyRequest"]


@pytest.mark.parametrize("action", ["dismiss", "reject"])
def test_dismiss_and_reject_lock_the_request(db_session, locks_taken, action):
    sar = _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 2}])
    locks_taken.clear()

    if action == "dismiss":
        shop_assembly_repository.dismiss_shop_assembly_openings(
            db_session, sar.id, None, dismissed_by="manager", reason=None
        )
    else:
        shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "manager", "not needed")

    assert locks_taken[:1] == ["ShopAssemblyRequest"]


def _two_openings_both_batched(session):
    """A request for A01 and A02, each on its own batch: closed out (APPROVED), nothing pending."""
    project = _project(session)
    _stock(session, project)
    sar = import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [
                {**_HINGE, "item_quantity": 2},
                {**_HINGE, "opening_number": "A02", "item_quantity": 2},
            ],
            "classifications": [{**_SHOP_HINGE, "classification": "SHOP_HARDWARE"}],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [{**_HINGE, "quantity": 2}, {**_HINGE, "opening_number": "A02", "quantity": 2}],
        },
    )["shop_assembly_request"]
    first = shop_assembly_repository.create_shop_assembly_batch(
        session, sar.id, batch_lines(session, sar.id, openings=["A01"]), created_by="manager"
    )
    shop_assembly_repository.create_shop_assembly_batch(
        session, sar.id, batch_lines(session, sar.id, openings=["A02"]), created_by="manager"
    )
    session.flush()
    return sar, first


def test_returning_a_cancelled_batch_locks_the_request(db_session, locks_taken):
    _sar, first = _two_openings_both_batched(db_session)
    locks_taken.clear()

    shop_assembly_repository.return_batch_to_pending(db_session, first)

    assert locks_taken[:1] == ["ShopAssemblyRequest"]


def test_cancelling_a_batch_pull_locks_request_then_pull_then_inventory(db_session, monkeypatch):
    """#1156: batch creation takes the request and then inventory; batch discard takes the request and
    then the pull. The cancel takes the request first too, then the pull, then inventory - any other
    order and a cancel racing a batch or a discard deadlocks."""
    from app.repositories import warehouse as warehouse_repository
    from app.repositories.warehouse import pull_requests

    _sar, first = _two_openings_both_batched(db_session)
    # Picked, so the cancel has rows to restock and locks inventory on the way.
    pick_pull(db_session, first.pull_request_id)
    db_session.flush()
    seen: list[str] = []
    real = pull_requests.lock_rows

    def spy(session, model_class, ids):
        seen.append(model_class.__name__)
        return real(session, model_class, ids)

    monkeypatch.setattr(pull_requests, "lock_rows", spy)
    monkeypatch.setattr(locking, "lock_rows", spy)

    warehouse_repository.cancel_pull_request(db_session, first.pull_request_id, "manager", "wrong pull")

    # request -> pull -> inventory: the order batch creation and batch discard take.
    assert "InventoryLocation" in seen
    assert seen.index("ShopAssemblyRequest") < seen.index("PullRequest") < seen.index("InventoryLocation")


def test_a_request_closed_under_a_cancel_is_reopened_with_its_returned_opening(db_session):
    """#1156: the cancel used to read the request unlocked. When a sibling batch closed it out after
    the cancel had read it as PENDING, the cancel flipped its opening back without reopening it, and the
    request sat APPROVED holding a pending opening nothing could reach. Read fresh under the lock, the
    request is seen closed and is reopened."""
    sar, first = _two_openings_both_batched(db_session)
    # The session still believes what it read before the sibling batch closed the request out.
    db_session.execute(
        update(ShopAssemblyRequest)
        .where(ShopAssemblyRequest.id == sar.id)
        .values(status=ShopAssemblyRequestStatus.PENDING)
        .execution_options(synchronize_session=False)
    )
    db_session.expire_all()
    stale = db_session.get(ShopAssemblyRequest, sar.id)
    assert stale.status == ShopAssemblyRequestStatus.PENDING
    db_session.execute(
        update(ShopAssemblyRequest)
        .where(ShopAssemblyRequest.id == sar.id)
        .values(status=ShopAssemblyRequestStatus.APPROVED)
        .execution_options(synchronize_session=False)
    )

    assert shop_assembly_repository.return_batch_to_pending(db_session, first) is True
    db_session.flush()
    db_session.expire_all()

    request = shop_assembly_repository.get_shop_assembly_request(db_session, sar.id)
    assert request.status == ShopAssemblyRequestStatus.PENDING
    assert {o.opening_number: o.status for o in request.openings} == {
        "A01": ShopAssemblyOpeningStatus.PENDING,
        "A02": ShopAssemblyOpeningStatus.BATCHED,
    }


def test_a_decision_made_while_waiting_on_the_lock_is_met_as_a_state_error(db_session):
    """What the second of two managers sees: the first one's reject has landed by the time the lock
    is theirs, and their batch reads the request fresh and is refused cleanly instead of racing it."""
    project = _project(db_session)
    _stock(db_session, project)
    sar = _finalize(db_session, project, [{**_HINGE, "quantity": 2}])
    lines = batch_lines(db_session, sar.id)
    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "first manager", "not needed")

    with pytest.raises(InvalidStateTransitionError):
        shop_assembly_repository.create_shop_assembly_batch(db_session, sar.id, lines, created_by="second manager")


def test_a_rejection_reason_longer_than_the_column_is_a_field_error(db_session):
    """#1208: refused cleanly, with the request left pending, instead of overflowing at flush."""
    project = _project(db_session)
    sar = _finalize(db_session, project, [{**_HINGE, "quantity": 2}])

    with pytest.raises(ValidationError) as exc:
        shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "manager", "x" * 501)
    assert exc.value.field == "reason"
    db_session.refresh(sar)
    assert sar.status.value == "PENDING"

    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "manager", "  " + "x" * 500 + "  ")
    db_session.refresh(sar)
    assert sar.status.value == "REJECTED"
    assert sar.rejection_reason == "x" * 500


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_a_rejection_needs_a_reason(db_session, reason):
    """#1242: as a shipping rejection does (#972), the request stays pending without one."""
    sar = _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 2}])

    with pytest.raises(ValidationError) as exc:
        shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "manager", reason)
    assert exc.value.field == "reason"
    db_session.refresh(sar)
    assert sar.status.value == "PENDING"


def test_a_rejection_tells_the_shop_why(db_session):
    """#1242: the shop assembly audience gets a notice carrying the request number and the reason."""
    from sqlalchemy import select

    from app.models.enums import NotificationType
    from app.models.notification import Notification
    from app.services import notification_service

    sar = _finalize(db_session, _project(db_session), [{**_HINGE, "quantity": 2}])
    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "manager", "frames not ready")

    notices = db_session.scalars(
        select(Notification).where(Notification.type == NotificationType.SHOP_ASSEMBLY_REQUEST_REJECTED)
    ).all()
    assert len(notices) == 1
    notice = notices[0]
    assert notice.project_id == sar.project_id
    assert notice.recipient_role == notification_service.SHOP_ASSEMBLY_RECIPIENT_ROLE
    assert notice.recipient_user_id is None
    assert sar.request_number in notice.message
    assert "frames not ready" in notice.message


def test_a_second_batch_takes_the_next_sequence(db_session):
    project = _project(db_session)
    _stock(db_session, project)
    sar = import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [
                {**_HINGE, "item_quantity": 2},
                {**_HINGE, "opening_number": "A02", "item_quantity": 2},
            ],
            "classifications": [{**_SHOP_HINGE, "classification": "SHOP_HARDWARE"}],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [{**_HINGE, "quantity": 2}, {**_HINGE, "opening_number": "A02", "quantity": 2}],
        },
    )["shop_assembly_request"]

    first = shop_assembly_repository.create_shop_assembly_batch(
        db_session, sar.id, batch_lines(db_session, sar.id, openings=["A01"]), created_by="manager"
    )
    second = shop_assembly_repository.create_shop_assembly_batch(
        db_session, sar.id, batch_lines(db_session, sar.id, openings=["A02"]), created_by="manager"
    )

    assert (first.sequence, second.sequence) == (1, 2)
