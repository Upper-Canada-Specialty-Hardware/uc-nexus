"""A shop-assembly request is held to the schedule (#1133), and its decisions lock it (#1121).

DB-backed like the rest of the suite: every test runs against a real Postgres in a rolled-back
transaction.
"""

import uuid
from datetime import datetime

import pytest

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.stock_item import StockItem
from app.repositories import import_repository, shop_assembly_repository, warehouse_admin_repository
from app.services import locking
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


def _finalize(session, project, sar_items, *, scheduled=4):
    """A01 scheduled for `scheduled` HG-100 hinges, and a request raised with `sar_items`."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [{**_HINGE, "item_quantity": scheduled}],
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
        shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "manager", None)

    assert locks_taken[:1] == ["ShopAssemblyRequest"]


def test_a_decision_made_while_waiting_on_the_lock_is_met_as_a_state_error(db_session):
    """What the second of two managers sees: the first one's reject has landed by the time the lock
    is theirs, and their batch reads the request fresh and is refused cleanly instead of racing it."""
    project = _project(db_session)
    _stock(db_session, project)
    sar = _finalize(db_session, project, [{**_HINGE, "quantity": 2}])
    lines = batch_lines(db_session, sar.id)
    shop_assembly_repository.reject_shop_assembly_request(db_session, sar.id, "first manager", None)

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
