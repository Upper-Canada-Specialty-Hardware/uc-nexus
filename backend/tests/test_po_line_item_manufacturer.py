"""POLineItem.manufacturer is derived (not stored) from the line's linked HardwareItem rows (issue
#232), loaded via selectinload so it's not an N+1. DB-backed - skipped when DATABASE_URL is unset."""

import uuid

from sqlalchemy import select

from app.models.purchase_order import PurchaseOrder
from app.repositories import import_repository, po_repository
from app.schemas.converters import po_line_item_to_type


def _make_project(session) -> PurchaseOrder:
    from app.models.project import Project

    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test", company="TUBC")
    session.add(p)
    session.flush()
    return p


def _import_draft_with_manufacturer(session, project, *, manufacturer):
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [{"opening_number": "A01"}],
            "hardware_items": [
                {
                    "opening_number": "A01",
                    "product_code": "HG-100",
                    "hardware_category": "HINGE",
                    "item_quantity": 1,
                    "manufacturer": manufacturer,
                }
            ],
            "po_drafts": [
                {
                    "po_number": None,
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [
                        {"hardware_category": "HINGE", "product_code": "HG-100", "order_as": "ALIAS-100"},
                    ],
                }
            ],
        },
    )
    session.flush()
    return session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).first()


def test_line_manufacturer_derived_from_linked_hardware(db_session):
    project = _make_project(db_session)
    draft = _import_draft_with_manufacturer(db_session, project, manufacturer="Acme Inc")

    # get_purchase_orders selectinloads line_items -> hardware_items, so the derived field is populated.
    po = po_repository.get_purchase_orders(db_session, project.id)[0]
    assert po_line_item_to_type(po.line_items[0]).manufacturer == "Acme Inc"
    # the single-PO loader derives it too
    po_single = po_repository.get_purchase_order(db_session, draft.id)
    assert po_line_item_to_type(po_single.line_items[0]).manufacturer == "Acme Inc"


def test_line_manufacturer_none_when_hardware_has_none(db_session):
    project = _make_project(db_session)
    draft = _import_draft_with_manufacturer(db_session, project, manufacturer=None)

    po = po_repository.get_purchase_order(db_session, draft.id)
    assert po_line_item_to_type(po.line_items[0]).manufacturer is None
