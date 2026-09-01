"""Raising a shipping-out request off inventory, and correcting one before it is accepted (#451).

The Shipping module can now compose a request itself. The rules it is held to are the ones the
request entity carries, not the ones the import wizard happened to apply, so these tests are mostly
about the two paths being the same path: the same reservation of stock (#342), the same refusal to
over-claim.

The edit is the other half. A request that cannot be corrected has to be rejected and retyped, and
these pin what an edit is allowed to do to a claim it already holds.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, InventoryShortfallError, ValidationError
from app.models.enums import ReservationSource, ShippingOutRequestStatus
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.pull_request import PullRequestItem
from app.models.stock_item import StockItem
from app.repositories import shipping_repository, shipping_requests, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _stock(session, project, *, qty=10, code="HG-100", cat="HINGE"):
    """Project inventory for a fixture, sourced from the stock pool - the cheapest valid origin
    (`ck_inventory_locations_has_origin` requires one)."""
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=cat,
        product_code=code,
        quantity=qty,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    il = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project.id,
        stock_item_id=si.id,
        warehouse_id=warehouse_id,
        hardware_category=cat,
        product_code=code,
        quantity=qty,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _loose(qty=2, code="HG-100", cat="HINGE", opening=None):
    return {
        "opening_number": opening,
        "hardware_category": cat,
        "product_code": code,
        "requested_quantity": qty,
    }


def _create(session, project, items, *, number=None, **kwargs):
    return shipping_requests.create_shipping_out_requests(
        session,
        project.id,
        [{"request_number": number or f"SOR-{uuid.uuid4().hex[:6]}", "items": items}],
        created_by="Shipper",
        **kwargs,
    )[0]


def _reserved(session, req) -> int:
    return warehouse_repository.get_reserved_total(session, ReservationSource.SHIPPING_OUT_REQUEST, req.id)


# --- raising one off inventory ----------------------------------------------------------------


def test_a_loose_line_needs_no_opening_at_all(db_session):
    # The whole point: shelf stock belongs to the project, not to a door. Before this the composer
    # had to invent an opening, which put a claim on the request the schedule never made.
    project = _project(db_session)
    _stock(db_session, project, qty=10)

    req = _create(db_session, project, [_loose(qty=3)])

    assert req.status == ShippingOutRequestStatus.PENDING
    assert req.created_by == "Shipper"
    assert [(i.opening_number, i.requested_quantity) for i in req.items] == [(None, 3)]


def test_it_reserves_what_it_claims_exactly_as_the_wizard_does(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=10)

    req = _create(db_session, project, [_loose(qty=4)])

    assert _reserved(db_session, req) == 4
    # And the reservation is what the next composer is measured against.
    assert warehouse_repository.get_available_quantities(db_session, project.id, [("HINGE", "HG-100")]) == {
        ("HINGE", "HG-100"): 6
    }


def test_over_claiming_the_shelf_is_refused_whole(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=2)

    with pytest.raises(InventoryShortfallError):
        _create(db_session, project, [_loose(qty=5)])


def test_stock_another_request_holds_is_not_free(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=5)
    _create(db_session, project, [_loose(qty=4)])

    with pytest.raises(InventoryShortfallError):
        _create(db_session, project, [_loose(qty=2)])


def test_an_empty_request_is_refused(db_session):
    project = _project(db_session)
    with pytest.raises(ValidationError):
        _create(db_session, project, [])


def test_a_line_must_name_a_product(db_session):
    project = _project(db_session)
    with pytest.raises(ValidationError):
        _create(db_session, project, [{"opening_number": None, "requested_quantity": 1}])


def test_the_server_mints_a_unique_number_whatever_the_caller_sends(db_session):
    """#493: duplicates are no longer possible to refuse, because they are no longer possible.

    The number used to be typed by hand, so two requests could collide and the create had to reject
    the second. The server mints it from the project's counter now and ignores what the caller sent,
    so the same string twice produces two distinct requests rather than a conflict.
    """
    project = _project(db_session)
    _stock(db_session, project, qty=10)

    first = _create(db_session, project, [_loose(qty=1)], number="SOR-DUP")
    second = _create(db_session, project, [_loose(qty=1)], number="SOR-DUP")

    assert first.request_number != second.request_number
    assert first.request_number.endswith("-001")
    assert second.request_number.endswith("-002")
    assert first.request_number.startswith(project.project_id)


# --- editing a pending one --------------------------------------------------------------------


def test_adding_a_line_claims_more_stock(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=10)
    _stock(db_session, project, qty=5, code="LK-9", cat="LOCK")
    req = _create(db_session, project, [_loose(qty=2)])

    shipping_requests.replace_shipping_out_request_items(
        db_session, req.id, [_loose(qty=2), _loose(qty=3, code="LK-9", cat="LOCK")]
    )

    refreshed = shipping_repository.get_shipping_out_request(db_session, req.id)
    assert sorted((i.product_code, i.requested_quantity) for i in refreshed.items) == [("HG-100", 2), ("LK-9", 3)]
    assert _reserved(db_session, req) == 5


def test_reducing_a_line_is_not_gated_against_stock_it_already_holds(db_session):
    # The bug this guards: releasing after the gate instead of before would measure a 4 -> 3 trim as
    # a request for 3 MORE, and the whole shelf is already spoken for by this very request.
    project = _project(db_session)
    _stock(db_session, project, qty=4)
    req = _create(db_session, project, [_loose(qty=4)])

    shipping_requests.replace_shipping_out_request_items(db_session, req.id, [_loose(qty=3)])

    assert _reserved(db_session, req) == 3
    assert warehouse_repository.get_available_quantities(db_session, project.id, [("HINGE", "HG-100")]) == {
        ("HINGE", "HG-100"): 1
    }


def test_an_edit_that_over_claims_is_refused_and_leaves_the_original_claim(db_session):
    # The edit deletes the old lines and releases the old claim BEFORE the gate, so what happens
    # when the gate refuses is the whole question: the caller must be left holding what it had.
    # A savepoint is exactly the shape of the resolver's transaction - it commits only on success.
    project = _project(db_session)
    _stock(db_session, project, qty=4)
    req = _create(db_session, project, [_loose(qty=2)])

    with pytest.raises(InventoryShortfallError), db_session.begin_nested():
        shipping_requests.replace_shipping_out_request_items(db_session, req.id, [_loose(qty=9)])

    refreshed = shipping_repository.get_shipping_out_request(db_session, req.id)
    assert [(i.product_code, i.requested_quantity) for i in refreshed.items] == [("HG-100", 2)]
    assert _reserved(db_session, req) == 2


def test_emptying_a_request_is_refused(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=10)
    req = _create(db_session, project, [_loose(qty=2)])

    with pytest.raises(ValidationError):
        shipping_requests.replace_shipping_out_request_items(db_session, req.id, [])


def test_an_accepted_request_cannot_be_edited(db_session):
    # Its lines are on a warehouse pull the floor may already be picking against a printed sheet.
    project = _project(db_session)
    _stock(db_session, project, qty=10)
    req = _create(db_session, project, [_loose(qty=2)])
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")

    with pytest.raises(InvalidStateTransitionError, match="must be Pending to edit"):
        shipping_requests.replace_shipping_out_request_items(db_session, req.id, [_loose(qty=1)])


def test_an_edited_request_carries_its_new_lines_onto_the_pull(db_session):
    project = _project(db_session)
    _stock(db_session, project, qty=10)
    req = _create(db_session, project, [_loose(qty=2)])
    shipping_requests.replace_shipping_out_request_items(db_session, req.id, [_loose(qty=5)])

    accepted = shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()

    lines = db_session.scalars(
        select(PullRequestItem).where(PullRequestItem.pull_request_id == accepted.pull_request_id)
    ).all()
    assert [(line.opening_number, line.requested_quantity) for line in lines] == [(None, 5)]
