"""Organising staged hardware into containers (#451).

The rules under test are all about physical objects rather than policy, which is why they are worth
pinning: a skid that cannot be strapped, a leaf that exists once, and loose stock that cannot be
placed twice over.
"""

import uuid
from datetime import datetime

import pytest

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    OpeningItemState,
    PullRequestItemType,
    PullRequestSource,
    PullRequestStatus,
    ShipmentContainerType,
)
from app.models.opening_item import OpeningItem
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.repositories import shipment_containers as containers
from app.repositories import warehouse_admin_repository


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _leaf(session, project, *, opening="101", leaf=1, state=OpeningItemState.SHIP_READY) -> OpeningItem:
    oi = OpeningItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=uuid.uuid4(),
        warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(session),
        opening_number=opening,
        leaf=leaf,
        quantity=1,
        assembly_completed_at=datetime.utcnow(),
        state=state,
    )
    session.add(oi)
    session.flush()
    return oi


def _staged_loose(session, project, *, code="HG-100", cat="HINGE", qty=4, opening="101"):
    """Loose stock reaches the staging pool by a COMPLETED shipping pull, which is what
    `get_ship_ready_items` counts. Building that is the only honest way to seed it."""
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
            item_type=PullRequestItemType.LOOSE,
            opening_number=opening,
            hardware_category=cat,
            product_code=code,
            requested_quantity=qty,
        )
    )
    session.flush()


def _container(session, project, *, kind=ShipmentContainerType.SKID, name="Skid 1"):
    return containers.create_container(session, project.id, container_type=kind, name=name, created_by="tester")


def _leaf_item(oi):
    return {
        "item_type": "OPENING_ITEM",
        "opening_item_id": str(oi.id),
        "opening_number": oi.opening_number,
        "leaf": oi.leaf,
        "hardware_category": "",
        "product_code": "",
        "quantity": 1,
    }


def _loose_item(qty, code="HG-100", cat="HINGE", opening="101"):
    return {
        "item_type": "LOOSE",
        "opening_item_id": None,
        "opening_number": opening,
        "leaf": None,
        "hardware_category": cat,
        "product_code": code,
        "quantity": qty,
    }


# --- the container itself ----------------------------------------------------------------------


def test_an_open_container_name_is_taken_only_while_it_is_open(db_session):
    project = _project(db_session)
    _container(db_session, project, name="Skid 1")
    with pytest.raises(ConflictError):
        _container(db_session, project, name="Skid 1")


def test_a_blank_name_is_refused(db_session):
    project = _project(db_session)
    with pytest.raises(ValidationError):
        _container(db_session, project, name="   ")


def test_breaking_down_a_container_returns_its_contents_to_the_pool(db_session):
    project = _project(db_session)
    oi = _leaf(db_session, project)
    container = _container(db_session, project)
    containers.set_container_items(db_session, container.id, [_leaf_item(oi)])

    assert containers.build_staged_pool(db_session, project.id)["leaves"][oi.id] == container.id
    containers.delete_container(db_session, container.id)
    assert containers.build_staged_pool(db_session, project.id)["leaves"][oi.id] is None


# --- what may be placed ------------------------------------------------------------------------


def test_a_leaf_that_is_not_staged_cannot_be_loaded(db_session):
    # IN_INVENTORY means assembled but not pulled for shipping - it is not on the floor yet.
    project = _project(db_session)
    oi = _leaf(db_session, project, state=OpeningItemState.IN_INVENTORY)
    container = _container(db_session, project)
    with pytest.raises(ValidationError, match="not staged"):
        containers.set_container_items(db_session, container.id, [_leaf_item(oi)])


def test_one_leaf_cannot_sit_in_two_containers(db_session):
    project = _project(db_session)
    oi = _leaf(db_session, project)
    first = _container(db_session, project, name="Skid 1")
    second = _container(db_session, project, name="Skid 2")
    containers.set_container_items(db_session, first.id, [_leaf_item(oi)])

    with pytest.raises(ConflictError, match="already in"):
        containers.set_container_items(db_session, second.id, [_leaf_item(oi)])


def test_the_same_leaf_twice_in_one_container_is_refused(db_session):
    project = _project(db_session)
    oi = _leaf(db_session, project)
    container = _container(db_session, project)
    with pytest.raises(ValidationError, match="cannot be placed twice"):
        containers.set_container_items(db_session, container.id, [_leaf_item(oi), _leaf_item(oi)])


def test_a_skid_stops_at_thirty_leaves(db_session):
    project = _project(db_session)
    leaves = [_leaf(db_session, project, opening=f"{n:03d}", leaf=1) for n in range(31)]
    container = _container(db_session, project)
    with pytest.raises(ValidationError, match="at most 30 door leaves"):
        containers.set_container_items(db_session, container.id, [_leaf_item(oi) for oi in leaves])


def test_a_door_cart_has_no_leaf_ceiling(db_session):
    # The thirty is a property of a skid, not of containers - a cart is loaded until it is full and
    # nothing in the system can know when that is.
    project = _project(db_session)
    leaves = [_leaf(db_session, project, opening=f"{n:03d}", leaf=1) for n in range(31)]
    cart = _container(db_session, project, kind=ShipmentContainerType.DOOR_CART, name="Cart 1")
    result = containers.set_container_items(db_session, cart.id, [_leaf_item(oi) for oi in leaves])
    assert len(result.items) == 31


def test_loose_placement_cannot_exceed_what_is_staged(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)
    container = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    with pytest.raises(ValidationError, match="only 4 staged"):
        containers.set_container_items(db_session, container.id, [_loose_item(9)])


def test_another_containers_placement_counts_against_what_is_free(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)
    first = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    second = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 2")
    containers.set_container_items(db_session, first.id, [_loose_item(3)])

    with pytest.raises(ValidationError, match="only 1 staged"):
        containers.set_container_items(db_session, second.id, [_loose_item(2)])


def test_re_saving_a_container_is_not_gated_against_what_it_already_holds(db_session):
    # The same release-before-measure trap the request edit had: without adding this container's own
    # units back, saving it unchanged would read as asking for them a second time.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)
    container = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(db_session, container.id, [_loose_item(4)])

    result = containers.set_container_items(db_session, container.id, [_loose_item(4)])
    assert [i.quantity for i in result.items] == [4]


# --- the stack ----------------------------------------------------------------------------------


def test_position_comes_from_the_list_order(db_session):
    project = _project(db_session)
    a = _leaf(db_session, project, opening="101", leaf=1)
    b = _leaf(db_session, project, opening="102", leaf=1)
    container = _container(db_session, project)

    result = containers.set_container_items(db_session, container.id, [_leaf_item(a), _leaf_item(b)])
    assert [(i.opening_number, i.position) for i in sorted(result.items, key=lambda i: i.position)] == [
        ("101", 0),
        ("102", 1),
    ]

    # Reordering is the same call with the list the other way round.
    result = containers.set_container_items(db_session, container.id, [_leaf_item(b), _leaf_item(a)])
    assert [(i.opening_number, i.position) for i in sorted(result.items, key=lambda i: i.position)] == [
        ("102", 0),
        ("101", 1),
    ]


def test_emptying_a_container_is_allowed(db_session):
    # Unlike a request, an empty container is a real state - it is a skid nobody has loaded yet.
    project = _project(db_session)
    oi = _leaf(db_session, project)
    container = _container(db_session, project)
    containers.set_container_items(db_session, container.id, [_leaf_item(oi)])

    result = containers.set_container_items(db_session, container.id, [])
    assert result.items == []
    assert containers.build_staged_pool(db_session, project.id)["leaves"][oi.id] is None


# --- shipping -----------------------------------------------------------------------------------


def test_shipping_stamps_the_slip_and_closes_the_containers(db_session):
    project = _project(db_session)
    oi = _leaf(db_session, project)
    _staged_loose(db_session, project, qty=2)
    skid = _container(db_session, project, name="Skid 1")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(db_session, skid.id, [_leaf_item(oi)])
    containers.set_container_items(db_session, box.id, [_loose_item(2)])

    slip = containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [skid.id, box.id],
        packing_slip_number=f"PS-{uuid.uuid4().hex[:6]}",
        shipped_by="shipper",
        details=None,
    )
    db_session.flush()

    assert {i.item_type for i in slip.items} == {
        PullRequestItemType.OPENING_ITEM,
        PullRequestItemType.LOOSE,
    }
    db_session.refresh(skid)
    db_session.refresh(box)
    assert skid.packing_slip_id == slip.id
    assert box.packing_slip_id == slip.id
    # The leaf went out with it.
    db_session.refresh(oi)
    assert oi.state == OpeningItemState.SHIPPED_OUT
    # And a shipped container is out of the staging workspace.
    assert containers.get_containers(db_session, project.id, open_only=True) == []


def test_an_empty_container_cannot_be_shipped(db_session):
    project = _project(db_session)
    container = _container(db_session, project)
    with pytest.raises(ValidationError, match="is empty"):
        containers.confirm_shipment_from_containers(
            db_session,
            project.id,
            [container.id],
            packing_slip_number=f"PS-{uuid.uuid4().hex[:6]}",
            shipped_by="shipper",
            details=None,
        )


def test_shipping_nothing_is_refused(db_session):
    project = _project(db_session)
    with pytest.raises(ValidationError, match="at least one container"):
        containers.confirm_shipment_from_containers(
            db_session,
            project.id,
            [],
            packing_slip_number=f"PS-{uuid.uuid4().hex[:6]}",
            shipped_by="shipper",
            details=None,
        )


def test_a_shipped_container_cannot_be_edited_or_broken_down(db_session):
    project = _project(db_session)
    oi = _leaf(db_session, project)
    container = _container(db_session, project)
    containers.set_container_items(db_session, container.id, [_leaf_item(oi)])
    containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [container.id],
        packing_slip_number=f"PS-{uuid.uuid4().hex[:6]}",
        shipped_by="shipper",
        details=None,
    )
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError, match="already shipped"):
        containers.set_container_items(db_session, container.id, [])
    with pytest.raises(InvalidStateTransitionError, match="already shipped"):
        containers.delete_container(db_session, container.id)
    with pytest.raises(InvalidStateTransitionError, match="already shipped"):
        containers.rename_container(db_session, container.id, "Skid 9")


def test_a_container_from_another_project_cannot_join_the_shipment(db_session):
    project = _project(db_session)
    other = _project(db_session)
    oi = _leaf(db_session, other)
    container = _container(db_session, other)
    containers.set_container_items(db_session, container.id, [_leaf_item(oi)])

    with pytest.raises(ValidationError, match="another project"):
        containers.confirm_shipment_from_containers(
            db_session,
            project.id,
            [container.id],
            packing_slip_number=f"PS-{uuid.uuid4().hex[:6]}",
            shipped_by="shipper",
            details=None,
        )


def test_a_missing_container_is_a_not_found(db_session):
    with pytest.raises(NotFoundError):
        containers.rename_container(db_session, uuid.uuid4(), "Skid 1")
