import uuid
from collections import defaultdict

from sqlalchemy import case, func, select
from sqlalchemy.orm import Session

from app.models.enums import POStatus
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.project import Opening as OpeningModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.shipping import PackingSlip as PackingSlipModel
from app.models.shipping import PackingSlipItem as PackingSlipItemModel


def get_hardware_summary(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    # Query 1: DRAFT POs — po_drafted quantities
    draft_stmt = (
        select(
            POLineItemModel.hardware_category,
            POLineItemModel.product_code,
            func.sum(POLineItemModel.ordered_quantity).label("po_drafted"),
        )
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            POModel.deleted_at.is_(None),
            POModel.status == POStatus.DRAFT,
        )
        .group_by(POLineItemModel.hardware_category, POLineItemModel.product_code)
    )
    if project_id is not None:
        draft_stmt = draft_stmt.where(POModel.project_id == project_id)
    draft_rows = session.execute(draft_stmt).all()

    # Query 2: Placed POs (ORDERED, PARTIALLY_RECEIVED, CLOSED) — ordered + received
    placed_stmt = (
        select(
            POLineItemModel.hardware_category,
            POLineItemModel.product_code,
            func.sum(POLineItemModel.ordered_quantity).label("ordered"),
            func.sum(POLineItemModel.received_quantity).label("received"),
            func.sum(
                case(
                    (
                        POModel.status.in_([POStatus.ORDERED, POStatus.PARTIALLY_RECEIVED]),
                        POLineItemModel.ordered_quantity - POLineItemModel.received_quantity,
                    ),
                    else_=0,
                )
            ).label("back_ordered"),
        )
        .join(POModel, POLineItemModel.po_id == POModel.id)
        .where(
            POModel.deleted_at.is_(None),
            POModel.status.in_([POStatus.ORDERED, POStatus.PARTIALLY_RECEIVED, POStatus.CLOSED]),
        )
        .group_by(POLineItemModel.hardware_category, POLineItemModel.product_code)
    )
    if project_id is not None:
        placed_stmt = placed_stmt.where(POModel.project_id == project_id)
    placed_rows = session.execute(placed_stmt).all()

    # Query 3: Shipped — packing slip quantities
    shipped_stmt = (
        select(
            PackingSlipItemModel.hardware_category,
            PackingSlipItemModel.product_code,
            func.sum(PackingSlipItemModel.quantity).label("shipped_out"),
        )
        .join(PackingSlipModel, PackingSlipItemModel.packing_slip_id == PackingSlipModel.id)
        .group_by(PackingSlipItemModel.hardware_category, PackingSlipItemModel.product_code)
    )
    if project_id is not None:
        shipped_stmt = shipped_stmt.where(PackingSlipModel.project_id == project_id)
    shipped_rows = session.execute(shipped_stmt).all()

    # Merge all by (hardware_category, product_code)
    merged: dict[tuple[str, str], dict] = defaultdict(
        lambda: {
            "hardware_category": "",
            "product_code": "",
            "po_drafted": 0,
            "ordered": 0,
            "received": 0,
            "back_ordered": 0,
            "shipped_out": 0,
        }
    )

    for row in draft_rows:
        key = (row.hardware_category, row.product_code)
        merged[key]["hardware_category"] = row.hardware_category
        merged[key]["product_code"] = row.product_code
        merged[key]["po_drafted"] = row.po_drafted or 0

    for row in placed_rows:
        key = (row.hardware_category, row.product_code)
        merged[key]["hardware_category"] = row.hardware_category
        merged[key]["product_code"] = row.product_code
        merged[key]["ordered"] = row.ordered or 0
        merged[key]["received"] = row.received or 0
        merged[key]["back_ordered"] = row.back_ordered or 0

    for row in shipped_rows:
        key = (row.hardware_category, row.product_code)
        merged[key]["hardware_category"] = row.hardware_category
        merged[key]["product_code"] = row.product_code
        merged[key]["shipped_out"] = row.shipped_out or 0

    return sorted(merged.values(), key=lambda r: (r["hardware_category"], r["product_code"]))


def get_opening_hardware_status(session: Session, project_id: uuid.UUID | None = None) -> list[dict]:
    stmt = (
        select(
            HardwareItemModel,
            OpeningModel.opening_number,
            OpeningModel.building,
            OpeningModel.floor,
            OpeningModel.location,
            POModel.status.label("po_status"),
        )
        .join(OpeningModel, HardwareItemModel.opening_id == OpeningModel.id)
        .outerjoin(POLineItemModel, HardwareItemModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(
            POModel,
            (POLineItemModel.po_id == POModel.id) & (POModel.deleted_at.is_(None)),
        )
        .order_by(OpeningModel.opening_number)
    )
    if project_id is not None:
        stmt = stmt.where(HardwareItemModel.project_id == project_id)
    rows = session.execute(stmt).all()

    openings: dict[str, dict] = {}
    for row in rows:
        hi = row[0]
        opening_number = row.opening_number
        building = row.building
        floor = row.floor
        location = row.location
        po_status = row.po_status

        if po_status == POStatus.DRAFT:
            status = "PO_DRAFTED"
        elif po_status in (POStatus.ORDERED, POStatus.PARTIALLY_RECEIVED):
            status = "ORDERED"
        elif po_status == POStatus.CLOSED:
            status = "RECEIVED"
        else:
            status = "PO_DRAFTED"

        if opening_number not in openings:
            openings[opening_number] = {
                "opening_number": opening_number,
                "building": building,
                "floor": floor,
                "location": location,
                "items": [],
            }

        openings[opening_number]["items"].append(
            {
                "hardware_category": hi.hardware_category,
                "product_code": hi.product_code,
                "item_quantity": hi.item_quantity,
                "status": status,
            }
        )

    return sorted(openings.values(), key=lambda o: o["opening_number"])
