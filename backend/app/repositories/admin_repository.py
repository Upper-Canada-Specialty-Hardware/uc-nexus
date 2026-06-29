import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import POStatus
from app.models.hardware import HardwareItem as HardwareItemModel
from app.models.project import Opening as OpeningModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel


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
        elif po_status in (POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED):
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
