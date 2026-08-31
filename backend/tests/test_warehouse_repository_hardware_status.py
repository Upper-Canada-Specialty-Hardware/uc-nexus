"""Tests for warehouse_repository.get_hardware_status_by_product."""

import uuid
from datetime import datetime
from decimal import Decimal

from app.models.enums import (
    HardwareItemState,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ShipmentStatus,
)
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.project import Opening, Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping import PackingSlip, PackingSlipItem
from app.models.stock_item import StockItem
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository

CAT = "HINGE"


def _make_project(session) -> Project:
    p = Project(
        id=uuid.uuid4(),
        project_id=f"PROJ-{uuid.uuid4().hex[:8]}",
        description="Test",
        company="TUBC",
    )
    session.add(p)
    session.flush()
    return p


def _make_opening(session, project_id: uuid.UUID, opening_number: str = "A01") -> Opening:
    o = Opening(id=uuid.uuid4(), project_id=project_id, opening_number=opening_number)
    session.add(o)
    session.flush()
    return o


def _make_hardware_item(
    session,
    *,
    project_id: uuid.UUID,
    opening_id: uuid.UUID,
    product_code: str,
    hardware_category: str = CAT,
    item_quantity: int = 1,
    state: HardwareItemState = HardwareItemState.AVAILABLE,
) -> HardwareItem:
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project_id,
        opening_id=opening_id,
        hardware_category=hardware_category,
        product_code=product_code,
        item_quantity=item_quantity,
        state=state,
    )
    session.add(hi)
    session.flush()
    return hi


def _make_po_with_line(
    session,
    *,
    project_id: uuid.UUID,
    status: POStatus,
    product_code: str,
    ordered_quantity: int,
    received_quantity: int = 0,
    deleted_at: datetime | None = None,
) -> PurchaseOrder:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        status=status,
        deleted_at=deleted_at,
        company="TUBC",
    )
    session.add(po)
    session.flush()
    session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category=CAT,
            product_code=product_code,
            ordered_quantity=ordered_quantity,
            received_quantity=received_quantity,
            unit_cost=Decimal("1.00"),
        )
    )
    session.flush()
    return po


def _make_pull(
    session,
    *,
    project_id: uuid.UUID,
    source: PullRequestSource,
    status: PullRequestStatus,
    lines: list[tuple[str | None, str, int]],
) -> PullRequest:
    """A pull with one line per (opening_number, product_code, quantity)."""
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"PR-{uuid.uuid4().hex[:6]}",
        project_id=project_id,
        source=source,
        status=status,
        requested_by="tester",
    )
    session.add(pr)
    session.flush()
    for opening_number, product_code, quantity in lines:
        session.add(
            PullRequestItem(
                id=uuid.uuid4(),
                pull_request_id=pr.id,
                opening_number=opening_number,
                hardware_category=CAT,
                product_code=product_code,
                requested_quantity=quantity,
            )
        )
    session.flush()
    return pr


def _make_slip(
    session,
    *,
    project_id: uuid.UUID,
    lines: list[tuple[str | None, str, int]],
) -> PackingSlip:
    ps = PackingSlip(
        id=uuid.uuid4(),
        packing_slip_number=f"PS-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        shipped_by="shipper",
        shipped_at=datetime.utcnow(),
        status=ShipmentStatus.SCHEDULED,
    )
    session.add(ps)
    session.flush()
    for opening_number, product_code, quantity in lines:
        session.add(
            PackingSlipItem(
                id=uuid.uuid4(),
                packing_slip_id=ps.id,
                opening_number=opening_number,
                hardware_category=CAT,
                product_code=product_code,
                quantity=quantity,
            )
        )
    session.flush()
    return ps


def _make_inventory(session, *, project_id: uuid.UUID, product_code: str, quantity: int) -> InventoryLocation:
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    si = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=CAT,
        product_code=product_code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(si)
    session.flush()
    loc = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=si.id,
        warehouse_id=warehouse_id,
        hardware_category=CAT,
        product_code=product_code,
        quantity=quantity,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(loc)
    session.flush()
    return loc


def _row(rows: list[dict], product_code: str) -> dict:
    return next(r for r in rows if r["product_code"] == product_code)


def test_empty_project_ids_returns_empty(db_session):
    assert warehouse_repository.get_hardware_status_by_product(db_session, []) == []


def test_sums_across_selected_projects_and_excludes_others(db_session):
    p1, p2, p3 = (_make_project(db_session) for _ in range(3))
    for p, qty in ((p1, 4), (p2, 6), (p3, 99)):
        o = _make_opening(db_session, p.id)
        _make_hardware_item(db_session, project_id=p.id, opening_id=o.id, product_code="HG-100", item_quantity=qty)
    _make_po_with_line(
        db_session, project_id=p1.id, status=POStatus.GP_REGISTERED, product_code="HG-100", ordered_quantity=3
    )
    _make_po_with_line(db_session, project_id=p2.id, status=POStatus.DRAFT, product_code="HG-100", ordered_quantity=2)
    _make_po_with_line(
        db_session, project_id=p3.id, status=POStatus.GP_REGISTERED, product_code="HG-100", ordered_quantity=50
    )

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [p1.id, p2.id])
    assert len(rows) == 1
    r = rows[0]
    assert r["required_quantity"] == 10
    assert r["on_order"] == 3
    assert r["po_drafted"] == 2


def test_not_purchased_follows_hardware_item_state(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=5
    )
    _make_hardware_item(
        db_session,
        project_id=project.id,
        opening_id=opening.id,
        product_code="HG-100",
        item_quantity=3,
        state=HardwareItemState.IN_PO,
    )

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    assert rows[0]["required_quantity"] == 8
    assert rows[0]["not_purchased"] == 5


def test_po_buckets_split_by_status(db_session):
    """Drafted, on-order remainder, and receipts land in their own columns; CLOSED shortfall vanishes."""
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=30
    )

    _make_po_with_line(
        db_session, project_id=project.id, status=POStatus.DRAFT, product_code="HG-100", ordered_quantity=4
    )
    _make_po_with_line(
        db_session,
        project_id=project.id,
        status=POStatus.PARTIALLY_RECEIVED,
        product_code="HG-100",
        ordered_quantity=10,
        received_quantity=6,
    )
    # CLOSED short: the 3 never-received units are not on order - they will never come.
    _make_po_with_line(
        db_session,
        project_id=project.id,
        status=POStatus.CLOSED,
        product_code="HG-100",
        ordered_quantity=7,
        received_quantity=4,
    )
    # Soft-deleted POs are invisible to every bucket.
    _make_po_with_line(
        db_session,
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        product_code="HG-100",
        ordered_quantity=50,
        received_quantity=25,
        deleted_at=datetime.utcnow(),
    )

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    r = rows[0]
    assert r["po_drafted"] == 4
    assert r["on_order"] == 4  # 10 - 6 on the PARTIALLY_RECEIVED PO only
    assert r["received_quantity"] == 10  # 6 + 4 across placed POs


def test_sent_to_shop_counts_only_completed_shop_pulls(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=20
    )

    _make_pull(
        db_session,
        project_id=project.id,
        source=PullRequestSource.SHOP_ASSEMBLY,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", "HG-100", 6), ("A02", "HG-100", 2)],
    )
    for status in (PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS, PullRequestStatus.CANCELLED):
        _make_pull(
            db_session,
            project_id=project.id,
            source=PullRequestSource.SHOP_ASSEMBLY,
            status=status,
            lines=[("A01", "HG-100", 9)],
        )

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    assert rows[0]["sent_to_shop"] == 8


def test_staged_nets_shipping_pulls_against_slips_per_opening(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=40
    )

    _make_pull(
        db_session,
        project_id=project.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        # A01 part-shipped, A02 over-shipped (a slip can carry more against a key than the pull
        # staged - e.g. legacy lines), unattributed (None) untouched.
        lines=[("A01", "HG-100", 10), ("A02", "HG-100", 3), (None, "HG-100", 5)],
    )
    _make_slip(
        db_session,
        project_id=project.id,
        lines=[("A01", "HG-100", 4), ("A02", "HG-100", 5)],
    )

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    r = rows[0]
    # A01: 10-4=6. A02: 3-5 clamps to 0, not -2. None-key: 5.
    assert r["staged_for_shipping"] == 11
    assert r["shipped_out"] == 9


def test_staged_does_not_net_across_projects(db_session):
    """Two projects staging and shipping the same (opening, product) key stay separate pools."""
    p1, p2 = _make_project(db_session), _make_project(db_session)
    for p in (p1, p2):
        o = _make_opening(db_session, p.id)
        _make_hardware_item(db_session, project_id=p.id, opening_id=o.id, product_code="HG-100", item_quantity=10)
    _make_pull(
        db_session,
        project_id=p1.id,
        source=PullRequestSource.SHIPPING_OUT,
        status=PullRequestStatus.COMPLETED,
        lines=[("A01", "HG-100", 6)],
    )
    # p2 shipped against the same key without a completed pull; p1's staged 6 must not absorb it.
    _make_slip(db_session, project_id=p2.id, lines=[("A01", "HG-100", 6)])

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [p1.id, p2.id])
    r = rows[0]
    assert r["staged_for_shipping"] == 6
    assert r["shipped_out"] == 6


def test_on_hand_sums_inventory_locations(db_session):
    project = _make_project(db_session)
    opening = _make_opening(db_session, project.id)
    _make_hardware_item(
        db_session, project_id=project.id, opening_id=opening.id, product_code="HG-100", item_quantity=10
    )
    _make_inventory(db_session, project_id=project.id, product_code="HG-100", quantity=7)
    _make_inventory(db_session, project_id=project.id, product_code="HG-100", quantity=2)

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    assert rows[0]["on_hand"] == 9


def test_product_without_schedule_row_still_appears(db_session):
    """Stock-allocated hardware that never sat on a schedule shows with required 0, not nothing."""
    project = _make_project(db_session)
    _make_inventory(db_session, project_id=project.id, product_code="STOCK-ONLY", quantity=5)

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    r = _row(rows, "STOCK-ONLY")
    assert r["required_quantity"] == 0
    assert r["not_purchased"] == 0
    assert r["on_hand"] == 5


def test_returned_to_project_units_are_reported_and_shipped_out_stays_gross(db_session):
    """A RETURN_TO_PROJECT unit is back in on_hand while still inside the gross shipped_out sum, so
    the rollup carries the returned count separately for readers that sum "where the units are"."""
    from sqlalchemy import select

    from app.models.enums import ReturnDisposition
    from app.models.shipping import PackingSlipItem as PSI
    from app.models.shipping import ShipmentReturn, ShipmentReturnItem

    project = _make_project(db_session)
    slip = _make_slip(db_session, project_id=project.id, lines=[("A01", "HG-100", 40)])
    psi = db_session.scalars(select(PSI).where(PSI.packing_slip_id == slip.id)).one()
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(db_session)

    ret = ShipmentReturn(
        id=uuid.uuid4(),
        packing_slip_id=slip.id,
        warehouse_id=warehouse_id,
        returned_by="tester",
        returned_at=datetime.utcnow(),
    )
    db_session.add(ret)
    db_session.flush()
    db_session.add(
        ShipmentReturnItem(
            id=uuid.uuid4(),
            shipment_return_id=ret.id,
            packing_slip_item_id=psi.id,
            disposition=ReturnDisposition.RETURN_TO_PROJECT,
            quantity=10,
            hardware_category=CAT,
            product_code="HG-100",
            opening_number="A01",
        )
    )
    db_session.flush()
    _make_inventory(db_session, project_id=project.id, product_code="HG-100", quantity=10)

    rows = warehouse_repository.get_hardware_status_by_product(db_session, [project.id])
    row = next(r for r in rows if r["product_code"] == "HG-100")
    assert row["shipped_out"] == 40
    assert row["returned_to_project"] == 10
    assert row["on_hand"] == 10
