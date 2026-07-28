"""Partial allocation at shop-assembly request creation.

Shop assembly stops being all-or-nothing. The creation gate used to refuse a request outright when
its full bill of hardware did not fit available inventory, so one leaf short of one hinge held up
every leaf behind it. The requester now assigns what is available to leaves, partially-covered leaves
stay in the request, and the send/don't-send call is theirs.

What that turns into on the server, and what is pinned here:

- `quantity` still means **owed** - the schedule's number, never reduced by scarcity.
- `allocated_quantity` is what was claimed, reserved and will be pulled.
- The gate now runs over the ALLOCATION, so it is no longer the shortfall gate; it is the **race**
  gate, and it still refuses the whole finalize when availability moved under the allocation.
- Short is `quantity - allocated_quantity`, derived, never stored.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InventoryShortfallError, ValidationError
from app.models.enums import NotificationType, ReservationSource, ShopAssemblyRequestStatus
from app.models.inventory import InventoryLocation
from app.models.inventory_reservation import InventoryReservation
from app.models.notification import Notification
from app.models.project import Project
from app.models.shop_assembly import ShopAssemblyOpening, ShopAssemblyOpeningItem
from app.models.stock_item import StockItem
from app.repositories import import_repository, warehouse_admin_repository

HINGE = ("HINGE", "HG-A1")
CLOSER = ("CLOSER", "CL-A1")


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _seed_inventory(session, project_id, *, category, code, quantity):
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=category,
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
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
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(il)
    session.flush()
    return il


def _opening_input(number):
    return {
        "opening_number": number,
        "building": "B1",
        "floor": "F1",
        "location": "Lobby",
        "location_to": None,
        "location_from": None,
        "hand": None,
        "width": None,
        "length": None,
        "door_thickness": None,
        "jamb_thickness": None,
        "door_type": None,
        "frame_type": None,
        "interior_exterior": None,
        "keying": None,
        "heading_no": None,
        "single_pair": None,
        "assignment_multiplier": None,
        "leaf_count": 1,
    }


def _finalize(session, project, sar_openings, *, request_number=None):
    """`sar_openings` is [(opening_number, leaf, [(category, code, owed, allocated_or_None), ...])]."""
    return import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input(number) for number, _, _ in sar_openings],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_request_number": request_number or f"SA-{uuid.uuid4().hex[:6]}",
            "shop_assembly_openings": [
                {
                    "opening_number": number,
                    "leaf": leaf,
                    "items": [
                        {
                            "hardware_category": cat,
                            "product_code": code,
                            "quantity": owed,
                            "allocated_quantity": allocated,
                        }
                        for cat, code, owed, allocated in lines
                    ],
                }
                for number, leaf, lines in sar_openings
            ],
        },
    )


def _sao_items(session, sar_id):
    return list(
        session.scalars(
            select(ShopAssemblyOpeningItem)
            .join(ShopAssemblyOpening, ShopAssemblyOpening.id == ShopAssemblyOpeningItem.shop_assembly_opening_id)
            .where(ShopAssemblyOpening.shop_assembly_request_id == sar_id)
        ).all()
    )


def _reservations(session, project_id):
    return list(
        session.scalars(select(InventoryReservation).where(InventoryReservation.project_id == project_id)).all()
    )


# --- the default: None means fully allocated -----------------------------------------------------


def test_omitted_allocation_means_fully_allocated(db_session):
    """A caller that predates the allocator - a test, a script, a tab loaded before the deploy - asks
    for the whole line and is held to the old all-or-nothing behaviour."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=4)

    result = _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, None)])])
    db_session.flush()

    items = _sao_items(db_session, result["shop_assembly_request"].id)
    assert [(i.quantity, i.allocated_quantity) for i in items] == [(4, 4)]


def test_omitted_allocation_still_bounces_when_it_does_not_fit(db_session):
    """The default is "ask for everything", so an old caller still gets the old refusal."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=1)

    with pytest.raises(InventoryShortfallError):
        _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, None)])])


# --- partial allocation --------------------------------------------------------------------------


def test_partial_allocation_keeps_owed_and_reserves_only_what_it_claimed(db_session):
    """The checklist keeps the schedule's number; the claim is the allocation. The difference is
    short, and it is derived from the two columns rather than stored anywhere."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=2)

    result = _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, 2)])])
    db_session.flush()

    (item,) = _sao_items(db_session, result["shop_assembly_request"].id)
    assert (item.quantity, item.allocated_quantity) == (4, 2)

    reservations = _reservations(db_session, project.id)
    assert len(reservations) == 1
    assert reservations[0].quantity == 2  # not 4 - the request never claimed the other two


def test_a_zero_line_is_legal_on_a_leaf_its_other_lines_cover(db_session):
    """A leaf can be missing one product entirely and still be worth sending: the cart has the rest
    of its hardware on it and the assembler has real work to do."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=4)
    _seed_inventory(db_session, project.id, category=CLOSER[0], code=CLOSER[1], quantity=0)

    result = _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, 4), (*CLOSER, 1, 0)])])
    db_session.flush()

    items = {i.product_code: i for i in _sao_items(db_session, result["shop_assembly_request"].id)}
    assert (items[HINGE[1]].quantity, items[HINGE[1]].allocated_quantity) == (4, 4)
    assert (items[CLOSER[1]].quantity, items[CLOSER[1]].allocated_quantity) == (1, 0)
    # Nothing is reserved for the line that got nothing.
    assert {(r.product_code, r.quantity) for r in _reservations(db_session, project.id)} == {(HINGE[1], 4)}


def test_scarcity_across_leaves_is_the_caller_decision_not_a_refusal(db_session):
    """Two leaves, four hinges: one whole leaf and one short one, both sent. This is the case the
    old gate refused outright."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=6)

    result = _finalize(
        db_session,
        project,
        [("A01", 1, [(*HINGE, 4, 4)]), ("A02", 1, [(*HINGE, 4, 2)])],
    )
    db_session.flush()

    sar = result["shop_assembly_request"]
    assert sar.status == ShopAssemblyRequestStatus.PENDING
    assert sorted(i.allocated_quantity for i in _sao_items(db_session, sar.id)) == [2, 4]
    # One reservation row per combo across the whole request, for the total allocated.
    assert [r.quantity for r in _reservations(db_session, project.id)] == [6]


# --- validation ----------------------------------------------------------------------------------


def test_allocation_above_owed_is_refused(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)

    with pytest.raises(ValidationError) as excinfo:
        _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, 5)])])
    assert "allocated_quantity" == excinfo.value.field


def test_negative_allocation_is_refused(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)

    with pytest.raises(ValidationError):
        _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, -1)])])


def test_a_leaf_with_nothing_allocated_at_all_is_refused(db_session):
    """An empty cart: nothing to pull, nothing to stage, nothing to assemble, and `complete_opening`
    would refuse it at the far end for having zero installed units. The wizard drops such leaves
    before submitting, so reaching here is a race or a non-UI caller - both better refused than
    turned into a work unit that can never be finished."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=10)

    with pytest.raises(ValidationError) as excinfo:
        _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, 0), (*CLOSER, 1, 0)])])
    assert "nothing to pull" in str(excinfo.value)

    db_session.rollback()
    assert _reservations(db_session, project.id) == []


# --- the gate is now the race gate ----------------------------------------------------------------


def test_allocation_beyond_what_is_available_is_still_refused_whole(db_session):
    """The allocator never asks for more than was free when it built its numbers, so this can only
    be a race - availability moved between load and send. Writing a claim on hardware that is not
    there would be worse than bouncing; the wizard refetches and rebuilds."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=2)

    with pytest.raises(InventoryShortfallError) as excinfo:
        _finalize(db_session, project, [("A01", 1, [(*HINGE, 8, 5)])])
    # Measured against the allocation, not the owed quantity: 5 asked for, 2 available.
    assert (excinfo.value.shortfalls[0].requested, excinfo.value.shortfalls[0].available) == (5, 2)

    db_session.rollback()
    assert _reservations(db_session, project.id) == []


# --- purchasing signal ----------------------------------------------------------------------------


def test_a_successful_short_send_tells_purchasing_about_the_gap(db_session):
    """A short combo is out of available stock by construction - the allocator only leaves a line
    short once that combo's pool is exhausted - so it is always a genuine purchasing signal, not
    somebody else's claim. It fires on the SUCCESS path; the refusal path stays for races."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=2)

    _finalize(db_session, project, [("A01", 1, [(*HINGE, 6, 2)])], request_number="SA-SHORT-1")
    db_session.flush()

    notifs = list(
        db_session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
            )
        ).all()
    )
    assert len(notifs) == 1
    assert "SA-SHORT-1" in notifs[0].message
    assert "short 4" in notifs[0].message
    # Not "couldn't be fulfilled": the request exists and nothing is blocked. Purchasing is being
    # told what the project is missing, not sent hunting for a stuck request.
    assert "was sent short" in notifs[0].message
    assert "couldn't be fulfilled" not in notifs[0].message


def test_a_fully_covered_send_tells_purchasing_nothing(db_session):
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=4)

    _finalize(db_session, project, [("A01", 1, [(*HINGE, 4, 4)])])
    db_session.flush()

    assert (
        db_session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
            )
        ).all()
        == []
    )


def test_short_across_two_leaves_is_one_notification_per_combo(db_session):
    """The signal purchasing acts on is "the project is N hinges short", not "leaf A02 is 2 short and
    leaf A03 is 4 short" - they order against the combo."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    _seed_inventory(db_session, project.id, category=CLOSER[0], code=CLOSER[1], quantity=1)

    _finalize(
        db_session,
        project,
        [
            ("A01", 1, [(*HINGE, 4, 4)]),
            ("A02", 1, [(*HINGE, 4, 1), (*CLOSER, 2, 1)]),
        ],
        request_number="SA-SHORT-2",
    )
    db_session.flush()

    notifs = list(
        db_session.scalars(
            select(Notification).where(
                Notification.project_id == project.id,
                Notification.type == NotificationType.INVENTORY_SHORTFALL,
            )
        ).all()
    )
    assert len(notifs) == 1
    assert "short 3" in notifs[0].message  # the hinges, summed across both leaves
    assert "short 1" in notifs[0].message  # the closers


# --- re-upload reconciliation ---------------------------------------------------------------------


def test_reupload_rebuilds_the_reservation_from_allocated_not_owed(db_session):
    """A re-upload that drops one of a request's openings rebuilds the claim from what survived.
    Rebuilding from `quantity` would inflate it into a claim on hardware this request never had."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=6)

    _finalize(
        db_session,
        project,
        [("A01", 1, [(*HINGE, 4, 4)]), ("A02", 1, [(*HINGE, 4, 2)])],
    )
    db_session.flush()
    assert [r.quantity for r in _reservations(db_session, project.id)] == [6]

    # A02 is gone from the new schedule; A01 survives holding its 4.
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [],
            "replace_schedule": True,
            "include_shop_assembly_request": False,
        },
    )
    db_session.flush()

    assert [r.quantity for r in _reservations(db_session, project.id)] == [4]


def test_reupload_of_a_fully_short_line_rebuilds_to_nothing_for_it(db_session):
    """A surviving leaf whose line got nothing holds nothing, and `create_reservations` drops the
    zero rather than writing a row the `quantity >= 1` constraint would refuse."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)
    _seed_inventory(db_session, project.id, category=CLOSER[0], code=CLOSER[1], quantity=0)

    _finalize(
        db_session,
        project,
        [("A01", 1, [(*HINGE, 4, 4), (*CLOSER, 2, 0)]), ("A02", 1, [(*HINGE, 2, 1)])],
    )
    db_session.flush()

    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01")],
            "hardware_items": [],
            "replace_schedule": True,
            "include_shop_assembly_request": False,
        },
    )
    db_session.flush()

    rows = _reservations(db_session, project.id)
    assert {(r.product_code, r.quantity) for r in rows} == {(HINGE[1], 4)}
    assert all(r.source is ReservationSource.SHOP_ASSEMBLY_REQUEST for r in rows)


def test_the_purchasing_signal_totals_a_combo_across_every_line(db_session):
    """Purchasing orders against the combo, so the numbers have to be what this request wanted of
    that product against what it got. Counting only the short lines reported a request that took 4
    hinges on one leaf and missed 3 on another as "need 4, 1 available", which is true of neither."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=5)

    _finalize(
        db_session,
        project,
        [("A01", 1, [(*HINGE, 4, 4)]), ("A02", 1, [(*HINGE, 4, 1)])],
        request_number="SA-SHORT-3",
    )
    db_session.flush()

    (notif,) = db_session.scalars(
        select(Notification).where(
            Notification.project_id == project.id,
            Notification.type == NotificationType.INVENTORY_SHORTFALL,
        )
    ).all()
    # 8 owed across the request, 5 claimed, 3 genuinely missing from the shelf.
    assert "need 8, 5 available (short 3)" in notif.message


def test_a_line_that_omits_the_allocation_is_still_counted_in_the_combo_total(db_session):
    """The None default means fully allocated, so such a line contributes owed == allocated and must
    not drag the combo's reported availability down."""
    project = _make_project(db_session)
    _seed_inventory(db_session, project.id, category=HINGE[0], code=HINGE[1], quantity=6)

    _finalize(
        db_session,
        project,
        [("A01", 1, [(*HINGE, 4, None)]), ("A02", 1, [(*HINGE, 4, 2)])],
        request_number="SA-SHORT-4",
    )
    db_session.flush()

    (notif,) = db_session.scalars(
        select(Notification).where(
            Notification.project_id == project.id,
            Notification.type == NotificationType.INVENTORY_SHORTFALL,
        )
    ).all()
    assert "need 8, 6 available (short 2)" in notif.message
