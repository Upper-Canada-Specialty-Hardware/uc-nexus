"""Branches of the money- and stock-moving paths that no other test asserts (#1348, from #1156).

Each test here pins one branch that could be removed or broken without any existing test noticing:
the claim a cancelled shipping pull leaves behind, the restock that has to rebuild a row the
schedule re-upload deleted, deficient units arriving through a receive, the refusal to ship more than
was staged, and a transfer that must leave deficient units where they are. The receive-approval
persist failure lives in test_receive_drafts.py, beside the resolver fixtures it needs.
"""

import uuid
from datetime import datetime
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.errors import ValidationError
from app.models.audit_log import InventoryAuditLog
from app.models.enums import (
    AuditAction,
    PoolKind,
    POStatus,
    PullRequestSource,
    PullRequestStatus,
    ReservationSource,
)
from app.models.inventory import InventoryLocation
from app.models.project import Project
from app.models.pull_request import PullRequest, PullRequestItem
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.stock_item import StockItem
from app.models.warehouse import Warehouse
from app.repositories import import_repository, shipping_repository, warehouse_admin_repository
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories.warehouse import reservations
from app.repositories.warehouse.receiving import create_receive
from tests.inventory_fixtures import define_location, make_il, wh_id
from tests.pick_helpers import pick_pull
from tests.shop_assembly_helpers import batch_request, with_schedule

HINGE = ("HINGE", "HG-100")


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _seed_row(session, project_id, *, quantity, code=HINGE[1]) -> InventoryLocation:
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session, company="TUBC")
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category=HINGE[0],
        product_code=code,
        quantity=0,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    session.add(stock)
    session.flush()
    row = InventoryLocation(
        id=uuid.uuid4(),
        project_id=project_id,
        stock_item_id=stock.id,
        warehouse_id=warehouse_id,
        hardware_category=HINGE[0],
        product_code=code,
        quantity=quantity,
        deficient_quantity=0,
        aisle="A",
        row="1",
        bay="1",
        received_at=datetime.utcnow(),
    )
    session.add(row)
    session.flush()
    return row


def _raise_shipping_request(session, project, *, qty, opening="A01"):
    result = import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": opening}],
            "hardware_items": [],
            "shipping_out_pr_drafts": [
                {
                    "request_number": f"SHIP-{uuid.uuid4().hex[:6]}",
                    "requested_by": "importer",
                    "items": [
                        {
                            "opening_number": opening,
                            "hardware_category": HINGE[0],
                            "product_code": HINGE[1],
                            "requested_quantity": qty,
                        }
                    ],
                }
            ],
        },
    )
    session.flush()
    return result["shipping_out_requests"][0]


def _held(session, request_id) -> int:
    return reservations.get_reserved_total(session, ReservationSource.SHIPPING_OUT_REQUEST, request_id)


# --- 1. a cancelled shipping pull and its request's claim ---------------------------------------


def test_cancelling_a_shipping_pull_re_reserves_its_request(db_session):
    """Sufficient stock after the restock: the request goes back to Pending holding its claim again,
    so the next accept cannot be beaten to the hardware by another request."""
    project = _make_project(db_session)
    _seed_row(db_session, project.id, quantity=10)
    req = _raise_shipping_request(db_session, project, qty=4)
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pick_pull(db_session, req.pull_request_id, "picker")
    assert _held(db_session, req.id) == 0, "the pick consumed the claim"

    result = warehouse_repository.cancel_pull_request(db_session, req.pull_request_id, "manager", "wrong pull")
    db_session.flush()

    assert result.reservations_recreated is True
    assert _held(db_session, req.id) == 4
    assert req.integrity_note is None


def test_cancelling_a_shipping_pull_that_cannot_re_reserve_says_so(db_session):
    """Shortfall after the restock: no claim is invented, and the request carries a note saying it
    holds none - otherwise it looks claimed and the re-raised pull comes up short with no warning."""
    project = _make_project(db_session)
    _seed_row(db_session, project.id, quantity=5)
    req = _raise_shipping_request(db_session, project, qty=4, opening="A01")
    other = _raise_shipping_request(db_session, project, qty=1, opening="A02")
    shipping_repository.accept_shipping_out_request(db_session, req.id, "acceptor")
    db_session.flush()
    pick_pull(db_session, req.pull_request_id, "picker")
    # Hand-simulate another request's claim growing over the units this cancel is about to return,
    # the way an edit or a second accept would while the pull sat picked.
    reservations.create_reservations(
        db_session, project.id, ReservationSource.SHIPPING_OUT_REQUEST, other.id, [(*HINGE, 4)]
    )
    db_session.flush()

    result = warehouse_repository.cancel_pull_request(db_session, req.pull_request_id, "manager", "wrong pull")
    db_session.flush()

    assert result.reservations_recreated is False
    assert _held(db_session, req.id) == 0
    assert req.integrity_note is not None
    assert result.integrity_note == req.integrity_note
    assert "holds no claim on inventory" in req.integrity_note
    assert "short" in req.integrity_note


# --- 2. restocking a cancelled pull when the combo's row is gone ---------------------------------


def _scheduled_shop_pull(session, project, *, unit_cost):
    """A shop-assembly pull for 4 hinges (2 openings x 2) whose schedule prices the hinge."""
    payload = with_schedule(
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}, {"opening_number": "A02"}],
            "hardware_items": [],
            "include_shop_assembly_request": True,
            "shop_assembly_items": [
                {"opening_number": o, "hardware_category": HINGE[0], "product_code": HINGE[1], "quantity": 2}
                for o in ("A01", "A02")
            ],
        }
    )
    for hi in payload["hardware_items"]:
        hi["unit_cost"] = unit_cost
    sar = import_repository.finalize_import_session(session, payload)["shop_assembly_request"]
    session.flush()
    batch = batch_request(session, sar.id)
    session.flush()
    return session.scalar(select(PullRequest).where(PullRequest.id == batch.pull_request_id))


def _pick_then_lose_every_row(session, project, *, unit_cost):
    row = _seed_row(session, project.id, quantity=10)
    pr = _scheduled_shop_pull(session, project, unit_cost=unit_cost)
    warehouse_repository.start_pull_request_pick(session, pr.id, "picker")
    session.flush()
    warehouse_repository.confirm_pick(
        session,
        pr.id,
        [
            warehouse_repository.PickLine(
                hardware_category=HINGE[0], product_code=HINGE[1], inventory_location_id=row.id, quantity=4
            )
        ],
        "picker",
    )
    session.flush()
    # A schedule re-upload deleted every row of the combo (pick lines go to NULL with it).
    for il in session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id,
            InventoryLocation.hardware_category == HINGE[0],
            InventoryLocation.product_code == HINGE[1],
        )
    ).all():
        session.delete(il)
    session.flush()
    session.expire_all()
    return pr


def _rows_for_combo(session, project_id):
    return list(
        session.scalars(
            select(InventoryLocation).where(
                InventoryLocation.project_id == project_id,
                InventoryLocation.hardware_category == HINGE[0],
                InventoryLocation.product_code == HINGE[1],
            )
        ).all()
    )


def test_a_cancel_rebuilds_a_deleted_row_at_the_schedules_cost(db_session):
    project = _make_project(db_session)
    pr = _pick_then_lose_every_row(db_session, project, unit_cost=12.5)

    result = warehouse_repository.cancel_pull_request(db_session, pr.id, "manager", "wrong pull")
    db_session.flush()

    assert [(r.product_code, r.quantity) for r in result.restocked] == [(HINGE[1], 4)]
    rows = _rows_for_combo(db_session, project.id)
    assert len(rows) == 1, "the restock re-materialised exactly one row"
    rebuilt = rows[0]
    assert rebuilt.quantity == 4
    assert rebuilt.unit_cost == Decimal("12.5"), "a null cost would value the returned units at zero"
    anchor = db_session.get(StockItem, rebuilt.stock_item_id)
    assert anchor.unit_cost == Decimal("12.5"), "the anchor pool row carries the restored units' own price"
    audits = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.action == AuditAction.PULL_RESTOCK,
                InventoryAuditLog.project_id == project.id,
            )
        ).all()
    )
    assert audits and all(a.detail.get("returnedToSourceRow") is False for a in audits)


def test_a_cancel_rebuilds_a_deleted_row_in_the_projects_own_company(db_session):
    project = _make_project(db_session)
    pr = _pick_then_lose_every_row(db_session, project, unit_cost=12.5)
    # Another tenant's primary building, older than any of TUBC's.
    db_session.add(
        Warehouse(
            id=uuid.uuid4(),
            company="UBC",
            name=f"Other {uuid.uuid4().hex[:6]}",
            code=f"O{uuid.uuid4().hex[:6]}",
            is_primary=True,
            is_active=True,
            created_at=datetime(2000, 1, 1),
            updated_at=datetime(2000, 1, 1),
        )
    )
    db_session.flush()

    warehouse_repository.cancel_pull_request(db_session, pr.id, "manager", "wrong pull")
    db_session.flush()

    rebuilt = _rows_for_combo(db_session, project.id)[0]
    assert db_session.get(Warehouse, rebuilt.warehouse_id).company == project.company


# --- 3. receiving deficient units across several locations ---------------------------------------


def _po(session, *, project_id, ordered, code, pool_kind=None) -> tuple[PurchaseOrder, POLineItem]:
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project_id,
        pool_kind=pool_kind,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
        company="TUBC",
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category=HINGE[0],
        product_code=code,
        ordered_quantity=ordered,
        received_quantity=0,
        unit_cost=Decimal("1.00"),
        gp_line_ord=1,
    )
    session.add(line)
    session.flush()
    return po, line


def test_a_project_receive_books_deficient_units_per_location_and_closes_the_po(db_session):
    project = _make_project(db_session)
    code = f"HG-{uuid.uuid4().hex[:6]}"
    po, line = _po(db_session, project_id=project.id, ordered=10, code=code)
    define_location(db_session, aisle="A", row="1", bay="1")
    define_location(db_session, aisle="B", row="1", bay="1")

    create_receive(
        db_session,
        po.id,
        "warehouse",
        [
            {
                "po_line_item_id": line.id,
                "quantity_received": 10,
                "locations": [
                    {"aisle": "A", "row": "1", "bay": "1", "quantity": 6, "deficient_quantity": 2},
                    {"aisle": "B", "row": "1", "bay": "1", "quantity": 4},
                ],
            }
        ],
        warehouse_id=wh_id(db_session),
    )
    db_session.flush()

    rows = list(db_session.scalars(select(InventoryLocation).where(InventoryLocation.po_line_item_id == line.id)).all())
    assert sorted((r.aisle, r.quantity, r.deficient_quantity) for r in rows) == [("A", 6, 2), ("B", 4, 0)]
    assert line.received_quantity == 10, "deficient units are received units"
    assert po.status == POStatus.CLOSED
    receive_audits = list(
        db_session.scalars(
            select(InventoryAuditLog).where(
                InventoryAuditLog.action == AuditAction.RECEIVE,
                InventoryAuditLog.entity_id.in_([r.id for r in rows]),
            )
        ).all()
    )
    assert len(receive_audits) == 2


def test_a_stock_receive_carries_its_deficient_units_onto_the_pool_row(db_session):
    code = f"HG-{uuid.uuid4().hex[:6]}"
    po, line = _po(db_session, project_id=None, ordered=10, code=code, pool_kind=PoolKind.STOCK)
    define_location(db_session, aisle="A", row="1", bay="1")

    create_receive(
        db_session,
        po.id,
        "warehouse",
        [
            {
                "po_line_item_id": line.id,
                "quantity_received": 6,
                "locations": [{"aisle": "A", "row": "1", "bay": "1", "quantity": 6, "deficient_quantity": 2}],
            }
        ],
        warehouse_id=wh_id(db_session),
    )
    db_session.flush()

    pool = list(db_session.scalars(select(StockItem).where(StockItem.product_code == code)).all())
    assert [(s.quantity, s.deficient_quantity) for s in pool] == [(6, 2)]
    assert po.status == POStatus.PARTIALLY_RECEIVED


# --- 5. shipping more than was staged ------------------------------------------------------------


def _stage(session, project_id, *, qty, opening="A01"):
    pr = PullRequest(
        id=uuid.uuid4(),
        request_number=f"SOR-{uuid.uuid4().hex[:6]}",
        project_id=project_id,
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
            hardware_category=HINGE[0],
            product_code=HINGE[1],
            requested_quantity=qty,
        )
    )
    session.flush()


def _line(quantity, **extra) -> dict:
    return {
        "opening_number": "A01",
        "hardware_category": HINGE[0],
        "product_code": HINGE[1],
        "quantity": quantity,
        **extra,
    }


def test_a_slip_cannot_ship_more_than_is_still_staged(db_session):
    project = _make_project(db_session)
    _stage(db_session, project.id, qty=3)
    shipping_repository.confirm_shipment(db_session, project.id, "shipper", [_line(3)])
    db_session.flush()

    with pytest.raises(ValidationError, match="requested 1, available 0") as exc:
        shipping_repository.confirm_shipment(db_session, project.id, "shipper", [_line(1)])
    assert exc.value.field == "items"


def test_a_manual_line_is_not_measured_against_the_staged_pool(db_session):
    project = _make_project(db_session)
    _stage(db_session, project.id, qty=3)
    shipping_repository.confirm_shipment(db_session, project.id, "shipper", [_line(3)])
    db_session.flush()

    slip = shipping_repository.confirm_shipment(db_session, project.id, "shipper", [_line(1, is_manual=True)])

    assert [(i.quantity, i.is_manual) for i in slip.items] == [(1, True)]


# --- 6. transferring a row that holds deficient units --------------------------------------------


def test_a_transfer_moves_only_sound_units_and_leaves_the_deficient_behind(db_session):
    project = _make_project(db_session)
    src = make_il(db_session, project, quantity=10, deficient=3, aisle="A", row="1", bay="1")
    define_location(db_session, src.warehouse_id, "B", "2", "2")
    kwargs = dict(
        source_type="INVENTORY_LOCATION",
        source_id=src.id,
        dest_warehouse_id=src.warehouse_id,
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    with pytest.raises(ValidationError) as exc:
        stock_repository.transfer_inventory(db_session, quantity=8, **kwargs)
    assert exc.value.field == "quantity"

    stock_repository.transfer_inventory(db_session, quantity=7, **kwargs)
    db_session.flush()

    assert (src.quantity, src.deficient_quantity) == (3, 3)
    dest = db_session.scalars(
        select(InventoryLocation).where(
            InventoryLocation.project_id == project.id,
            InventoryLocation.aisle == "B",
        )
    ).one()
    assert (dest.quantity, dest.deficient_quantity) == (7, 0)
