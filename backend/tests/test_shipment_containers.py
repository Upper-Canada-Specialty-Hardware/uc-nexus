"""Organising staged hardware into containers (#451).

The rules under test are about physical objects rather than policy, which is why they are worth
pinning: stock that cannot be placed twice over, and a stack whose order somebody has to reverse at
the far end.
"""

import uuid

import pytest

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import (
    PullRequestSource,
    PullRequestStatus,
    ShipmentContainerType,
)
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.repositories import shipment_containers as containers


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


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
            opening_number=opening,
            hardware_category=cat,
            product_code=code,
            requested_quantity=qty,
        )
    )
    session.flush()


def _container(session, project, *, kind=ShipmentContainerType.SKID, name="Skid 1"):
    return containers.create_container(session, project.id, container_type=kind, name=name, created_by="tester")


def _loose_item(qty, code="HG-100", cat="HINGE", opening="101"):
    return {
        "opening_number": opening,
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
    _staged_loose(db_session, project, qty=4)
    container = _container(db_session, project)
    containers.set_container_items(db_session, container.id, [_loose_item(4)])

    key = ("101", "HINGE", "HG-100")
    assert containers.build_staged_pool(db_session, project.id)[key]["placed"] == 4
    containers.delete_container(db_session, container.id)
    assert containers.build_staged_pool(db_session, project.id)[key]["placed"] == 0


# --- what may be placed ------------------------------------------------------------------------


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
    _staged_loose(db_session, project, qty=1, opening="101")
    _staged_loose(db_session, project, qty=1, opening="102")
    container = _container(db_session, project)
    a = _loose_item(1, opening="101")
    b = _loose_item(1, opening="102")

    result = containers.set_container_items(db_session, container.id, [a, b])
    assert [(i.opening_number, i.position) for i in sorted(result.items, key=lambda i: i.position)] == [
        ("101", 0),
        ("102", 1),
    ]

    # Reordering is the same call with the list the other way round.
    result = containers.set_container_items(db_session, container.id, [b, a])
    assert [(i.opening_number, i.position) for i in sorted(result.items, key=lambda i: i.position)] == [
        ("102", 0),
        ("101", 1),
    ]


def test_emptying_a_container_is_allowed(db_session):
    # Unlike a request, an empty container is a real state - it is a skid nobody has loaded yet.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)
    container = _container(db_session, project)
    containers.set_container_items(db_session, container.id, [_loose_item(4)])

    result = containers.set_container_items(db_session, container.id, [])
    assert result.items == []
    assert containers.build_staged_pool(db_session, project.id)[("101", "HINGE", "HG-100")]["placed"] == 0


# --- shipping -----------------------------------------------------------------------------------


def test_shipping_stamps_the_slip_and_closes_the_containers(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2, opening="101")
    _staged_loose(db_session, project, qty=3, opening="102")
    skid = _container(db_session, project, name="Skid 1")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(db_session, skid.id, [_loose_item(3, opening="102")])
    containers.set_container_items(db_session, box.id, [_loose_item(2)])

    slip = containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [skid.id, box.id],
        shipped_by="shipper",
        details=None,
    )
    db_session.flush()

    assert sorted((i.opening_number, i.quantity) for i in slip.items) == [("101", 2), ("102", 3)]
    db_session.refresh(skid)
    db_session.refresh(box)
    assert skid.packing_slip_id == slip.id
    assert box.packing_slip_id == slip.id
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
            shipped_by="shipper",
            details=None,
        )


def test_a_shipped_container_cannot_be_edited_or_broken_down(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)
    container = _container(db_session, project)
    containers.set_container_items(db_session, container.id, [_loose_item(4)])
    containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [container.id],
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
    _staged_loose(db_session, other, qty=4)
    container = _container(db_session, other)
    containers.set_container_items(db_session, container.id, [_loose_item(4)])

    with pytest.raises(ValidationError, match="another project"):
        containers.confirm_shipment_from_containers(
            db_session,
            project.id,
            [container.id],
            shipped_by="shipper",
            details=None,
        )


def test_a_missing_container_is_a_not_found(db_session):
    with pytest.raises(NotFoundError):
        containers.rename_container(db_session, uuid.uuid4(), "Skid 1")


# --- two openings, one product -------------------------------------------------------------------
# The staged pool is grouped by (opening, category, product), and so is the availability check the
# confirm applies. A container path keyed on the product alone reads as harmless until the same
# product is staged for two openings, at which point the two numbers become one and disagree with
# what the confirm will accept.


def _pool_loose(session, project):
    return containers.build_staged_pool(session, project.id)


def test_two_openings_staging_one_product_are_two_quantities(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4, opening="101")
    _staged_loose(db_session, project, qty=3, opening="102")

    pool = _pool_loose(db_session, project)
    assert pool[("101", "HINGE", "HG-100")]["staged"] == 4
    assert pool[("102", "HINGE", "HG-100")]["staged"] == 3


def test_placing_one_openings_units_leaves_the_others_alone(db_session):
    # Keyed on the product alone, placing 4 for 101 would read as 4 placed against the 3 staged for
    # 102 as well, and the second placement would be refused with stock sitting on the floor.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4, opening="101")
    _staged_loose(db_session, project, qty=3, opening="102")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")

    containers.set_container_items(db_session, box.id, [_loose_item(4, opening="101")])

    pool = _pool_loose(db_session, project)
    assert pool[("101", "HINGE", "HG-100")]["placed"] == 4
    assert pool[("102", "HINGE", "HG-100")]["placed"] == 0


def test_one_openings_staged_stock_cannot_cover_another_openings_placement(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4, opening="101")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")

    with pytest.raises(ValidationError, match="for opening 102"):
        containers.set_container_items(db_session, box.id, [_loose_item(1, opening="102")])


def test_the_same_pull_split_over_two_pulls_sums_rather_than_replacing(db_session):
    # Two completed pulls for the same opening and product are two rows out of get_ship_ready_items.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4, opening="101")
    _staged_loose(db_session, project, qty=2, opening="101")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")

    containers.set_container_items(db_session, box.id, [_loose_item(6, opening="101")])

    assert _pool_loose(db_session, project)[("101", "HINGE", "HG-100")]["staged"] == 6


def test_a_product_can_be_split_across_two_containers(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4, opening="101")
    first = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    second = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 2")

    containers.set_container_items(db_session, first.id, [_loose_item(2)])
    containers.set_container_items(db_session, second.id, [_loose_item(2)])

    pool = _pool_loose(db_session, project)
    assert pool[("101", "HINGE", "HG-100")]["placed"] == 4


def test_unattributed_stock_is_its_own_bucket(db_session):
    # A pull raised straight off inventory has no opening to attribute (#451), and those units are
    # not everyone's to spend.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=3, opening=None)
    _staged_loose(db_session, project, qty=2, opening="101")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")

    containers.set_container_items(db_session, box.id, [_loose_item(3, opening=None)])

    pool = _pool_loose(db_session, project)
    assert pool[(None, "HINGE", "HG-100")]["placed"] == 3
    assert pool[("101", "HINGE", "HG-100")]["placed"] == 0


def test_the_same_container_named_twice_ships_once(db_session):
    # Building the item list twice would double every quantity on the slip, and the confirm would
    # be gated against a staged pool it had already spent.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4, opening="101")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(db_session, box.id, [_loose_item(4)])

    slip = containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [box.id, box.id],
        shipped_by="shipper",
        details=None,
    )
    db_session.flush()

    assert sorted((i.opening_number, i.quantity) for i in slip.items) == [("101", 4)]


# --- the slip remembers how it was loaded --------------------------------------------------------
# `items` says what shipped; the Delivery Request also has to say which skid to open and in what
# order it was stacked, which is only answerable from the containers themselves.


def test_a_shipped_slip_carries_its_containers(db_session):
    project = _project(db_session)
    _staged_loose(db_session, project, qty=2, opening="101")
    _staged_loose(db_session, project, qty=1, opening="102")
    skid = _container(db_session, project, name="Skid 1")
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(db_session, skid.id, [_loose_item(1, opening="102")])
    containers.set_container_items(db_session, box.id, [_loose_item(2)])

    slip = containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [skid.id, box.id],
        shipped_by="shipper",
        details=None,
    )
    db_session.flush()
    db_session.refresh(slip)

    assert sorted(c.name for c in slip.containers) == ["Box 1", "Skid 1"]
    by_name = {c.name: c for c in slip.containers}
    assert [i.opening_number for i in by_name["Skid 1"].items] == ["102"]
    assert [i.quantity for i in by_name["Box 1"].items] == [2]


def test_the_stacking_order_survives_onto_the_slip(db_session):
    # Position is the whole point of a skid section on the Delivery Request. If it did not come back
    # with the slip, a reprint would list the stack in an arbitrary order.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=1, opening="101")
    _staged_loose(db_session, project, qty=1, opening="102")
    skid = _container(db_session, project, name="Skid 1")
    first = _loose_item(1, opening="101")
    second = _loose_item(1, opening="102")
    containers.set_container_items(db_session, skid.id, [second, first])

    slip = containers.confirm_shipment_from_containers(
        db_session,
        project.id,
        [skid.id],
        shipped_by="shipper",
        details=None,
    )
    db_session.flush()
    db_session.refresh(slip)

    loaded = sorted(slip.containers[0].items, key=lambda i: i.position)
    assert [i.opening_number for i in loaded] == ["102", "101"]


# --- manual lines -------------------------------------------------------------------------------
# A free-text, off-inventory line typed straight into a container: hardware on the truck that was
# never in Nexus inventory. It rides the same items list but touches none of the staged-pool
# arithmetic and is not returnable.


def _manual_item(qty=1, code="MAN-1", cat="MISC", opening=None):
    return {
        "opening_number": opening,
        "hardware_category": cat,
        "product_code": code,
        "quantity": qty,
        "is_manual": True,
    }


def test_a_manual_line_needs_no_staged_stock(db_session):
    # Nothing staged at all, yet a manual line places fine - it was never in inventory.
    project = _project(db_session)
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    result = containers.set_container_items(db_session, box.id, [_manual_item(3)])
    assert [(i.product_code, i.is_manual, i.quantity) for i in result.items] == [("MAN-1", True, 3)]


def test_a_manual_line_missing_its_product_or_category_is_refused(db_session):
    project = _project(db_session)
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    with pytest.raises(ValidationError, match="hardware category and a product code"):
        containers.set_container_items(
            db_session,
            box.id,
            [
                {
                    "opening_number": None,
                    "hardware_category": "MISC",
                    "product_code": "",
                    "quantity": 1,
                    "is_manual": True,
                }
            ],
        )


def test_a_manual_line_does_not_consume_a_real_products_staged_pool(db_session):
    # A manual line keyed the same as a real staged product must not read as placed against it, so a
    # real drag remains entitled to the whole staged quantity.
    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)  # (101, HINGE, HG-100)
    manual_box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(
        db_session, manual_box.id, [_manual_item(5, code="HG-100", cat="HINGE", opening="101")]
    )

    assert _pool_loose(db_session, project)[("101", "HINGE", "HG-100")]["placed"] == 0

    real_box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 2")
    result = containers.set_container_items(db_session, real_box.id, [_loose_item(4)])
    assert [i.quantity for i in result.items if not i.is_manual] == [4]


def test_a_shipped_manual_line_does_not_understate_the_staged_pool(db_session):
    # After shipping a real 2 plus a manual 5 keyed the same, the pool still shows 2 staged
    # (4 fulfilled - 2 real shipped); the manual 5 is not subtracted.
    from app.repositories import shipping_repository

    project = _project(db_session)
    _staged_loose(db_session, project, qty=4)
    box = _container(db_session, project, kind=ShipmentContainerType.BOX, name="Box 1")
    containers.set_container_items(
        db_session, box.id, [_loose_item(2), _manual_item(5, code="HG-100", cat="HINGE", opening="101")]
    )
    slip = containers.confirm_shipment_from_containers(
        db_session, project.id, [box.id], shipped_by="shipper", details=None
    )
    db_session.flush()

    # The manual line rode onto the slip flagged is_manual.
    assert sorted((i.product_code, i.is_manual) for i in slip.items) == [("HG-100", False), ("HG-100", True)]

    ready = shipping_repository.get_ship_ready_items(db_session, project.id)
    by_key = {
        (li["opening_number"], li["hardware_category"], li["product_code"]): li["available_quantity"]
        for li in ready["loose_items"]
    }
    assert by_key[("101", "HINGE", "HG-100")] == 2


def test_a_slip_cut_without_containers_simply_has_none(db_session):
    # Every shipment before #451, and the returns path, still have to read back.
    from app.repositories import shipping_repository

    project = _project(db_session)
    _staged_loose(db_session, project, qty=1, opening="101")
    slip = shipping_repository.confirm_shipment(
        db_session,
        project.id,
        "shipper",
        [{"opening_number": "101", "hardware_category": "HINGE", "product_code": "HG-100", "quantity": 1}],
        None,
    )
    db_session.flush()
    db_session.refresh(slip)

    assert slip.containers == []
