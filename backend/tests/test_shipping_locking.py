"""Shipping decisions and confirms are made against locked, freshly read rows (#1107).

Two people on the same Shipments or Requests board can press the same button at the same moment.
A real race cannot be staged inside one test transaction, so these pin the two things the fix is
made of: the lock is taken before the check it protects, and the check reads what another
transaction wrote rather than a copy the session already held. The second is simulated with a
Core UPDATE that leaves the session's identity map untouched, which is exactly the state the
loser of a race would be in.
"""

import uuid

import pytest
from sqlalchemy import event, update

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ShipmentContainerType,
    ShippingOutRequestStatus,
)
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.shipment_container import ShipmentContainer
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.repositories import shipment_containers as containers
from app.repositories import shipping_repository, shipping_requests


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _staged_loose(session, project, *, qty=4, opening="101"):
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            opening_number=opening,
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=qty,
        )
    )
    session.flush()


def _line(qty, opening="101"):
    return {"opening_number": opening, "hardware_category": "HINGE", "product_code": "HG-100", "quantity": qty}


def _request(session, project, status=ShippingOutRequestStatus.PENDING) -> ShippingOutRequest:
    req = ShippingOutRequest(
        id=uuid.uuid4(),
        request_number=f"{project.project_id}-{uuid.uuid4().hex[:4]}",
        project_id=project.id,
        status=status,
        created_by="tester",
    )
    session.add(req)
    session.flush()
    session.add(
        ShippingOutRequestItem(
            id=uuid.uuid4(),
            shipping_out_request_id=req.id,
            opening_number="101",
            hardware_category="HINGE",
            product_code="HG-100",
            requested_quantity=1,
        )
    )
    session.flush()
    return req


@pytest.fixture
def statements(db_session):
    """Every SQL statement the session sends, in order."""
    seen: list[str] = []
    connection = db_session.connection()

    def _record(conn, cursor, statement, parameters, context, executemany):
        seen.append(" ".join(statement.split()))

    event.listen(connection, "before_cursor_execute", _record)
    yield seen
    event.remove(connection, "before_cursor_execute", _record)


def _first(seen: list[str], *needles: str) -> int:
    for index, statement in enumerate(seen):
        if all(needle in statement for needle in needles):
            return index
    raise AssertionError(f"no statement with {needles}")


# --- C1: the staged pool -----------------------------------------------------------------------


def test_a_container_confirm_locks_the_pool_and_the_containers_before_reading_the_pool(db_session, statements):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2)
    box = containers.create_container(
        db_session, project.id, container_type=ShipmentContainerType.BOX, name="Box 1", created_by="t"
    )
    containers.set_container_items(db_session, box.id, [_line(2)])
    statements.clear()

    containers.confirm_shipment_from_containers(db_session, project.id, [box.id], shipped_by="s", details=None)

    pool_lock = _first(statements, "FROM projects", "FOR NO KEY UPDATE")
    container_lock = _first(statements, "FROM shipment_containers", "FOR UPDATE")
    pool_read = _first(statements, "FROM pull_request_items")
    assert pool_lock < container_lock < pool_read


def test_a_container_save_locks_the_pool_before_reading_it(db_session, statements):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2)
    box = containers.create_container(
        db_session, project.id, container_type=ShipmentContainerType.BOX, name="Box 1", created_by="t"
    )
    statements.clear()

    containers.set_container_items(db_session, box.id, [_line(2)])

    assert _first(statements, "FROM projects", "FOR NO KEY UPDATE") < _first(statements, "FROM pull_request_items")


def test_a_second_confirm_of_the_same_containers_is_refused_once_the_first_has_landed(db_session):
    """The loser of the race already held the container from before the winner committed. Re-read
    under the lock, it sees the winner's slip and refuses, instead of minting a second slip and
    moving the containers onto it."""
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2)
    box = containers.create_container(
        db_session, project.id, container_type=ShipmentContainerType.BOX, name="Box 1", created_by="t"
    )
    containers.set_container_items(db_session, box.id, [_line(2)])
    winner = containers.confirm_shipment_from_containers(db_session, project.id, [box.id], shipped_by="s", details=None)
    db_session.flush()

    # Put the session back in the loser's position: it still believes the container is open.
    db_session.execute(
        update(ShipmentContainer)
        .where(ShipmentContainer.id == box.id)
        .values(packing_slip_id=None)
        .execution_options(synchronize_session=False)
    )
    db_session.expire_all()
    db_session.get(ShipmentContainer, box.id)
    db_session.execute(
        update(ShipmentContainer)
        .where(ShipmentContainer.id == box.id)
        .values(packing_slip_id=winner.id)
        .execution_options(synchronize_session=False)
    )

    with pytest.raises(InvalidStateTransitionError, match="already shipped"):
        containers.confirm_shipment_from_containers(db_session, project.id, [box.id], shipped_by="s", details=None)


# --- V1: no negative lines ---------------------------------------------------------------------


def test_a_negative_container_line_is_refused_even_when_the_lines_net_to_nothing(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2)
    box = containers.create_container(
        db_session, project.id, container_type=ShipmentContainerType.BOX, name="Box 1", created_by="t"
    )
    with pytest.raises(ValidationError, match="at least 1"):
        containers.set_container_items(db_session, box.id, [_line(-5), _line(5)])


def test_a_zero_container_line_is_refused(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2)
    box = containers.create_container(
        db_session, project.id, container_type=ShipmentContainerType.BOX, name="Box 1", created_by="t"
    )
    with pytest.raises(ValidationError, match="at least 1"):
        containers.set_container_items(db_session, box.id, [_line(0)])


def test_the_confirm_refuses_a_non_positive_line(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2)
    with pytest.raises(ValidationError, match="at least 1"):
        shipping_repository.confirm_shipment(db_session, project.id, "s", [_line(-1), _line(2)])


# --- C2: request decisions ---------------------------------------------------------------------


def _decided_elsewhere(session, req, status):
    """Load the request into the session, then change it behind the session's back."""
    session.get(ShippingOutRequest, req.id)
    session.execute(
        update(ShippingOutRequest)
        .where(ShippingOutRequest.id == req.id)
        .values(status=status)
        .execution_options(synchronize_session=False)
    )


def test_accept_takes_a_row_lock_on_the_request(db_session, statements):
    project = _project(db_session)
    req = _request(db_session, project)
    statements.clear()

    shipping_repository.accept_shipping_out_request(db_session, req.id, "manager")

    _first(statements, "FROM shipping_out_requests", "FOR UPDATE")


def test_a_request_accepted_elsewhere_cannot_be_accepted_again(db_session):
    """Two managers accepting at once minted two pulls. The second now reads APPROVED."""
    project = _project(db_session)
    req = _request(db_session, project)
    _decided_elsewhere(db_session, req, ShippingOutRequestStatus.APPROVED)

    with pytest.raises(InvalidStateTransitionError, match="Pending to accept"):
        shipping_repository.accept_shipping_out_request(db_session, req.id, "manager")


def test_a_request_accepted_elsewhere_cannot_then_be_rejected(db_session):
    """An accept racing a reject released the claim the new pull relied on."""
    project = _project(db_session)
    req = _request(db_session, project)
    _decided_elsewhere(db_session, req, ShippingOutRequestStatus.APPROVED)

    with pytest.raises(InvalidStateTransitionError, match="Pending to reject"):
        shipping_repository.reject_shipping_out_request(db_session, req.id, "manager", "no truck")


def test_a_request_reopened_elsewhere_cannot_be_reopened_again(db_session):
    project = _project(db_session)
    req = _request(db_session, project, status=ShippingOutRequestStatus.APPROVED)
    _decided_elsewhere(db_session, req, ShippingOutRequestStatus.PENDING)

    with pytest.raises(InvalidStateTransitionError, match="Approved to reopen"):
        shipping_repository.reopen_shipping_out_request(db_session, req.id)


def test_a_request_accepted_elsewhere_cannot_be_edited(db_session):
    project = _project(db_session)
    req = _request(db_session, project)
    _decided_elsewhere(db_session, req, ShippingOutRequestStatus.APPROVED)

    with pytest.raises(InvalidStateTransitionError, match="Pending to edit"):
        shipping_requests.replace_shipping_out_request_items(
            db_session,
            req.id,
            [
                {
                    "opening_number": "101",
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "requested_quantity": 1,
                }
            ],
        )
