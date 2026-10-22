"""Allocating pool stock to a project names a pair on the project's schedule (#1647).

Units allocated under a pair the schedule does not use land on the project, but no shop assembly or
shipping out request can claim them. The server now refuses that pair; a non-schedule type code is
exempt, and a project with no schedule yet takes the units as floating inventory (ruled on #1756).
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest

from app.errors import ValidationError
from app.models.enums import (
    HardwareItemState,
    POStatus,
    PullPickLineState,
    PullRequestSource,
    PullRequestStatus,
    ShipmentStatus,
)
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.inventory_item_type import InventoryItemType
from app.models.project import Opening
from app.models.pull_pick_line import PullPickLine
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping import PackingSlip, PackingSlipItem
from app.repositories import stock as stock_repository
from app.repositories.warehouse import get_scheduled_pairs

from .inventory_fixtures import make_project, make_stock_item, wh_id


def _schedule(session, project, *pairs: tuple) -> None:
    """A schedule of one opening holding each (category, code, quantity[, beyond]).

    `beyond` is how many of the row's units a revision left past the schedule (#1491): an ordered row,
    so IN_PO, as `restate_beyond_schedule` leaves one.
    """
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"O-{uuid.uuid4().hex[:4]}")
    session.add(opening)
    session.flush()
    for category, code, quantity, *beyond in pairs:
        session.add(
            HardwareItem(
                id=uuid.uuid4(),
                project_id=project.id,
                opening_id=opening.id,
                hardware_category=category,
                product_code=code,
                item_quantity=quantity,
                beyond_schedule_quantity=beyond[0] if beyond else 0,
                state=HardwareItemState.IN_PO if beyond else HardwareItemState.AVAILABLE,
            )
        )
    session.flush()


def _allocate(session, si, project, category, code, quantity=2):
    return stock_repository.allocate_stock_to_project(
        session,
        stock_item_id=si.id,
        project_id=project.id,
        target_hardware_category=category,
        target_product_code=code,
        quantity=quantity,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
    )


# --- the server rule ---------------------------------------------------------------------------


def test_a_pair_off_the_schedule_is_refused(db_session):
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 4))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-999")

    with pytest.raises(ValidationError) as exc:
        _allocate(db_session, si, project, "HINGE", "HG-999")

    assert exc.value.field == "target_product_code"
    assert "not on this project's hardware schedule" in exc.value.message
    db_session.refresh(si)
    assert si.quantity == 10


def test_the_right_code_under_the_wrong_category_is_refused(db_session):
    """The pool row's own pair is the dialog's old default; the schedule has the code as a LOCK."""
    project = make_project(db_session)
    _schedule(db_session, project, ("LOCK", "HG-100", 4))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    with pytest.raises(ValidationError):
        _allocate(db_session, si, project, "HINGE", "HG-100")


def test_a_pair_on_the_schedule_is_allocated(db_session):
    project = make_project(db_session)
    _schedule(db_session, project, ("LOCK", "HG-100", 4))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    row = _allocate(db_session, si, project, "LOCK", "HG-100")

    assert (row.hardware_category, row.product_code, row.quantity) == ("LOCK", "HG-100", 2)


def test_a_non_schedule_type_code_is_exempt(db_session):
    """Frames, specialties and consumables are on no schedule by design."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 4))
    code = f"T{uuid.uuid4().hex[:6].upper()}"
    db_session.add(InventoryItemType(id=uuid.uuid4(), company=project.company, code=code, name=f"Frames {code}"))
    db_session.flush()
    si = make_stock_item(db_session, quantity=10, category=code, code="FR-3070")

    row = _allocate(db_session, si, project, code, "FR-3070")

    assert row.hardware_category == code


def test_another_companys_type_code_is_not_exempt(db_session):
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 4))
    code = f"T{uuid.uuid4().hex[:6].upper()}"
    db_session.add(InventoryItemType(id=uuid.uuid4(), company="UCSH", code=code, name=f"Specs {code}"))
    db_session.flush()
    si = make_stock_item(db_session, quantity=10, category=code, code="SP-1")

    with pytest.raises(ValidationError):
        _allocate(db_session, si, project, code, "SP-1")


def test_a_project_with_no_schedule_takes_floating_inventory(db_session):
    """Ruled on #1756: allowed, the units are tied to no schedule line until somebody ties them."""
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-999")

    row = _allocate(db_session, si, project, "HINGE", "HG-999")

    assert row.quantity == 2


def test_a_pair_the_latest_schedule_dropped_is_refused(db_session):
    """#1825: a revision dropped HG-OLD after it was ordered; its rows stay, every unit past the schedule."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 4), ("HINGE", "HG-OLD", 3, 3))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-OLD")

    with pytest.raises(ValidationError) as exc:
        _allocate(db_session, si, project, "HINGE", "HG-OLD")

    assert exc.value.field == "target_product_code"
    db_session.refresh(si)
    assert si.quantity == 10


def test_the_inventory_chip_still_counts_a_dropped_pair(db_session):
    """Only the allocation check leaves a dropped pair out; the chip's read is unchanged (#1825)."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 4), ("HINGE", "HG-OLD", 3, 3))

    assert get_scheduled_pairs(db_session, project.id) == {("HINGE", "HG-100"), ("HINGE", "HG-OLD")}
    assert get_scheduled_pairs(db_session, project.id, still_scheduled=True) == {("HINGE", "HG-100")}


def test_a_pair_the_schedule_still_asks_units_of_is_allocated(db_session):
    """Lowered, not dropped: one of HG-100's rows is past the schedule, the other still scheduled."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 2, 2), ("HINGE", "HG-100", 3, 1))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    row = _allocate(db_session, si, project, "HINGE", "HG-100")

    assert (row.product_code, row.quantity) == ("HG-100", 2)


def test_a_schedule_that_dropped_every_pair_is_still_a_schedule(db_session):
    """Only surplus rows left is not "no schedule imported yet" (#1756): the allocation is refused."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-OLD", 3, 3))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-OLD")

    with pytest.raises(ValidationError):
        _allocate(db_session, si, project, "HINGE", "HG-OLD")


# --- the targets the dialog picks from ---------------------------------------------------------


def _held(session, project, category, code, quantity, deficient=0):
    session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=make_stock_item(session, quantity=quantity, category=category, code=code).id,
            warehouse_id=wh_id(session),
            hardware_category=category,
            product_code=code,
            quantity=quantity,
            deficient_quantity=deficient,
            received_at=datetime.utcnow(),
        )
    )
    session.flush()


def _on_order(session, project, category, code, ordered, received=0):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"PO-REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        company=project.company,
    )
    session.add(po)
    session.flush()
    session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=category,
            product_code=code,
            ordered_quantity=ordered,
            received_quantity=received,
            unit_cost=Decimal("10.00"),
        )
    )
    session.flush()


def test_targets_say_what_each_pair_still_needs(db_session):
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 10), ("LOCK", "HG-100", 3), ("CLOSER", "CL-1", 2))
    _held(db_session, project, "HINGE", "HG-100", 4, deficient=1)  # 3 sound
    _on_order(db_session, project, "HINGE", "HG-100", ordered=5, received=0)
    _held(db_session, project, "CLOSER", "CL-1", 5)  # more than required
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    targets = stock_repository.get_allocation_targets(db_session, stock_item_id=si.id, project_id=project.id)

    assert targets["schedule_hardware"] is True
    assert targets["has_schedule"] is True
    needed = {(p["hardware_category"], p["product_code"]): p["still_needed_quantity"] for p in targets["pairs"]}
    assert needed == {("HINGE", "HG-100"): 10 - 3 - 5, ("LOCK", "HG-100"): 3, ("CLOSER", "CL-1"): 0}


def test_targets_leave_out_a_pair_the_latest_schedule_dropped(db_session):
    """#1825: HG-OLD is only surplus now; offering it as "0 still needed" invites the allocation #1647 stops."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 4), ("HINGE", "HG-OLD", 3, 3), ("LOCK", "LK-1", 2, 1))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-OLD")

    targets = stock_repository.get_allocation_targets(db_session, stock_item_id=si.id, project_id=project.id)

    assert targets["has_schedule"] is True
    required = {(p["hardware_category"], p["product_code"]): p["required_quantity"] for p in targets["pairs"]}
    assert required == {("HINGE", "HG-100"): 4, ("LOCK", "LK-1"): 1}


def test_targets_when_the_schedule_dropped_every_pair(db_session):
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-OLD", 3, 3))
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-OLD")

    targets = stock_repository.get_allocation_targets(db_session, stock_item_id=si.id, project_id=project.id)

    assert (targets["has_schedule"], targets["pairs"]) == (True, [])


def test_targets_on_a_project_with_no_schedule(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)

    targets = stock_repository.get_allocation_targets(db_session, stock_item_id=si.id, project_id=project.id)

    assert (targets["has_schedule"], targets["pairs"]) == (False, [])


def test_targets_for_a_type_code_pool_row(db_session):
    project = make_project(db_session)
    code = f"T{uuid.uuid4().hex[:6].upper()}"
    db_session.add(InventoryItemType(id=uuid.uuid4(), company=project.company, code=code, name=f"Frames {code}"))
    db_session.flush()
    si = make_stock_item(db_session, quantity=10, category=code, code="FR-3070")

    targets = stock_repository.get_allocation_targets(db_session, stock_item_id=si.id, project_id=project.id)

    assert targets["schedule_hardware"] is False


def _pulled(session, project, source, status, category, code, quantity, *, applied=None):
    """A pull of `quantity` units whose pick already took them off the shelf. `applied` adds the pick
    lines a pull still in progress carries."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        source=source,
        status=status,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    session.add(
        PullRequestItem(
            id=uuid.uuid4(),
            pull_request_id=pr.id,
            opening_number=None,
            hardware_category=category,
            product_code=code,
            requested_quantity=quantity,
        )
    )
    if applied:
        session.add(
            PullPickLine(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                hardware_category=category,
                product_code=code,
                quantity=applied,
                state=PullPickLineState.APPLIED,
                entered_by="picker",
                applied_at=datetime.utcnow(),
            )
        )
    session.flush()


def _slipped(session, project, category, code, quantity):
    slip = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.DELIVERED,
    )
    session.add(slip)
    session.flush()
    session.add(
        PackingSlipItem(
            id=uuid.uuid4(),
            packing_slip_id=slip.id,
            opening_number=None,
            hardware_category=category,
            product_code=code,
            quantity=quantity,
        )
    )
    session.flush()


def _needed(session, project, si) -> dict:
    targets = stock_repository.get_allocation_targets(session, stock_item_id=si.id, project_id=project.id)
    return {(p["hardware_category"], p["product_code"]): p["still_needed_quantity"] for p in targets["pairs"]}


def test_hardware_staged_for_a_truck_is_not_still_needed(db_session):
    """#1814: all 10 picked into staging leaves nothing on hand, on order or shipped, and is covered."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 10))
    _pulled(db_session, project, PullRequestSource.SHIPPING_OUT, PullRequestStatus.COMPLETED, "HINGE", "HG-100", 10)
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    assert _needed(db_session, project, si) == {("HINGE", "HG-100"): 0}


def test_picked_hardware_is_counted_once_wherever_it_is(db_session):
    """Staged and then partly slipped, pulled to the shop, or picked on a pull not yet handed over:
    each unit counts once, so what is left is exactly what no pick and no shelf covers."""
    project = make_project(db_session)
    _schedule(db_session, project, ("HINGE", "HG-100", 20))
    _pulled(db_session, project, PullRequestSource.SHIPPING_OUT, PullRequestStatus.COMPLETED, "HINGE", "HG-100", 6)
    _slipped(db_session, project, "HINGE", "HG-100", 2)  # 2 shipped, 4 still staged
    _pulled(db_session, project, PullRequestSource.SHOP_ASSEMBLY, PullRequestStatus.COMPLETED, "HINGE", "HG-100", 3)
    _pulled(
        db_session,
        project,
        PullRequestSource.SHOP_ASSEMBLY,
        PullRequestStatus.IN_PROGRESS,
        "HINGE",
        "HG-100",
        5,
        applied=2,
    )
    _pulled(db_session, project, PullRequestSource.SHIPPING_OUT, PullRequestStatus.CANCELLED, "HINGE", "HG-100", 4)
    si = make_stock_item(db_session, quantity=10, category="HINGE", code="HG-100")

    assert _needed(db_session, project, si) == {("HINGE", "HG-100"): 20 - 6 - 3 - 2}
