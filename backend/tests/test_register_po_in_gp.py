"""Register an imported Draft PO into GP (issue #175): po_repository.register_po_in_gp."""

import uuid

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import POStatus
from app.models.hardware import HardwareItem
from app.models.project import Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.vendor import Vendor
from app.repositories import import_repository, po_repository


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_vendor(session, name: str = "Acme", gp_vendor_id: str | None = None) -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}", gp_vendor_id=gp_vendor_id)
    session.add(v)
    session.flush()
    return v


def _opening_input(opening_number: str) -> dict:
    return {
        "opening_number": opening_number,
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
    }


def _hardware_item_input(opening_number: str, product_code: str) -> dict:
    return {
        "opening_number": opening_number,
        "product_code": product_code,
        "hardware_category": "HINGE",
        "item_quantity": 1,
        "unit_cost": 10.0,
        "unit_price": None,
        "list_price": None,
        "vendor_discount": None,
        "markup_pct": None,
        "vendor_no": "V1",
        "phase_code": None,
        "item_category_code": None,
        "product_group_code": None,
        "submittal_id": None,
    }


def _import_draft_po(session, project: Project, imported_vendor: Vendor) -> PurchaseOrder:
    """Create a realistic imported Draft PO with two line items, each backed by a HardwareItem (the import
    path links HardwareItem.po_line_item_id but never sets po_number, so it lands as DRAFT)."""
    import_repository.finalize_import_session(
        session,
        {
            "project_id": str(project.id),
            "openings": [_opening_input("A01"), _opening_input("A02")],
            "hardware_items": [
                _hardware_item_input("A01", "HG-100"),
                _hardware_item_input("A02", "HG-200"),
            ],
            "po_drafts": [
                {
                    "po_number": None,
                    "vendor_id": str(imported_vendor.id),
                    "notes": None,
                    "hardware_item_refs": [
                        {"opening_number": "A01", "product_code": "HG-100", "hardware_category": "HINGE"},
                        {"opening_number": "A02", "product_code": "HG-200", "hardware_category": "HINGE"},
                    ],
                    "line_item_aliases": [
                        {"hardware_category": "HINGE", "product_code": "HG-100", "order_as": "ALIAS-100"},
                        {"hardware_category": "HINGE", "product_code": "HG-200", "order_as": "ALIAS-200"},
                    ],
                }
            ],
        },
    )
    session.flush()
    po = session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).first()
    assert po is not None
    assert po.status == POStatus.DRAFT
    assert po.po_number is None
    return po


def test_register_keeps_all_lines_and_advances(db_session):
    project = _make_project(db_session)
    imported_vendor = _make_vendor(db_session, "Imported")  # not GP-linked
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = {li.product_code: li for li in po.line_items}

    gp_vendor = _make_vendor(db_session, "GP Vendor", gp_vendor_id="GPV1")

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        vendor_id=gp_vendor.id,
        po_number="  PO0000099  ",
        gp_company="  TUBC  ",
        cost_code="  210-200-2  ",
        line_items=[
            {
                "id": str(lines["HG-100"].id),
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 1,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": "ALIAS-100",
            },
            {
                "id": str(lines["HG-200"].id),
                "hardware_category": "HINGE",
                "product_code": "HG-200",
                "ordered_quantity": 1,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": "ALIAS-200",
            },
        ],
    )
    db_session.flush()
    db_session.refresh(po)

    assert po.status == POStatus.GP_REGISTERED
    assert po.po_number == "PO0000099"  # trimmed
    assert po.gp_company == "TUBC"
    assert po.vendor_id == gp_vendor.id
    assert po.cost_code == "210-200-2"
    assert po.ordered_at is not None

    by_code = {li.product_code: li for li in db_session.scalars(select(POLineItem).where(POLineItem.po_id == po.id))}
    # gp_line_ord is assigned positionally in payload order (GP POP10110.ORD = index * 16384).
    assert by_code["HG-100"].gp_line_ord == 16384
    assert by_code["HG-200"].gp_line_ord == 32768


def test_register_add_edit_and_remove_lines(db_session):
    project = _make_project(db_session)
    imported_vendor = _make_vendor(db_session, "Imported")
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = {li.product_code: li for li in po.line_items}
    kept_id = lines["HG-100"].id
    dropped_id = lines["HG-200"].id

    gp_vendor = _make_vendor(db_session, "GP Vendor", gp_vendor_id="GPV1")

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        vendor_id=gp_vendor.id,
        po_number="PO0000100",
        gp_company="TUBC",
        cost_code="310-000-3",
        line_items=[
            # keep HG-100 but edit qty + cost + order_as
            {
                "id": str(kept_id),
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 5,
                "unit_cost": 99.99,
                "classification": None,
                "order_as": "EDITED-100",
            },
            # add a brand-new line (no id)
            {
                "id": None,
                "hardware_category": "LOCK",
                "product_code": "NEW-300",
                "ordered_quantity": 2,
                "unit_cost": 4.5,
                "classification": None,
                "order_as": "ALIAS-300",
            },
            # HG-200 omitted -> removed
        ],
    )
    db_session.flush()

    by_code = {li.product_code: li for li in db_session.scalars(select(POLineItem).where(POLineItem.po_id == po.id))}
    assert set(by_code) == {"HG-100", "NEW-300"}

    kept = by_code["HG-100"]
    assert kept.id == kept_id  # same row, updated in place
    assert kept.ordered_quantity == 5
    assert float(kept.unit_cost) == 99.99
    assert kept.order_as == "EDITED-100"
    assert kept.gp_line_ord == 16384

    added = by_code["NEW-300"]
    assert added.gp_line_ord == 32768

    # the dropped line is gone, and its imported HardwareItem is orphaned (po_line_item_id -> NULL),
    # not deleted, so no FK violation and the hardware row survives.
    assert db_session.get(POLineItem, dropped_id) is None
    hw = {
        hi.product_code: hi
        for hi in db_session.scalars(select(HardwareItem).where(HardwareItem.project_id == project.id))
    }
    assert hw["HG-200"].po_line_item_id is None
    assert hw["HG-100"].po_line_item_id == kept_id


def test_register_rejects_non_draft(db_session):
    project = _make_project(db_session)
    imported_vendor = _make_vendor(db_session, "Imported")
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = {li.product_code: li for li in po.line_items}
    gp_vendor = _make_vendor(db_session, "GP Vendor", gp_vendor_id="GPV1")

    payload = [
        {
            "id": str(li.id),
            "hardware_category": li.hardware_category,
            "product_code": li.product_code,
            "ordered_quantity": 1,
            "unit_cost": 10.0,
            "classification": None,
            "order_as": li.order_as or "X",
        }
        for li in lines.values()
    ]

    po_repository.register_po_in_gp(
        db_session, po.id, vendor_id=gp_vendor.id, po_number="PO0000101", gp_company="TUBC", line_items=payload
    )
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        po_repository.register_po_in_gp(
            db_session, po.id, vendor_id=gp_vendor.id, po_number="PO0000101", gp_company="TUBC", line_items=payload
        )


def test_register_rejects_non_gp_vendor(db_session):
    # mapping a registered PO to a vendor with no GP link breaks the "GP-registered PO maps to a GP
    # vendor" invariant - reject it server-side, not just in the dialog's vendor list.
    project = _make_project(db_session)
    imported_vendor = _make_vendor(db_session, "Imported")  # gp_vendor_id is None
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = list(po.line_items)

    with pytest.raises(ValidationError):
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            vendor_id=imported_vendor.id,
            po_number="PO0000200",
            gp_company="TUBC",
            line_items=[
                {
                    "id": str(lines[0].id),
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "ordered_quantity": 1,
                    "unit_cost": 10.0,
                    "classification": None,
                    "order_as": "ALIAS-100",
                }
            ],
        )


def test_register_rejects_duplicate_po_number_in_project(db_session):
    # a reused GP number must surface as a clean ValidationError before commit, not a raw
    # IntegrityError that aborts the txn and orphans the GP PO the relay already created.
    project = _make_project(db_session)
    gp_vendor = _make_vendor(db_session, "GP Vendor", gp_vendor_id="GPV1")
    line = {
        "hardware_category": "HINGE",
        "product_code": "HG-1",
        "ordered_quantity": 1,
        "unit_cost": 1.0,
        "classification": None,
        "order_as": "X",
    }
    # an existing GP-registered PO in this project already owns the number
    po_repository.create_po(
        db_session,
        line_items=[line],
        project_id=project.id,
        vendor_id=gp_vendor.id,
        po_number="PO-DUP-1",
        gp_company="TUBC",
    )
    # a second draft in the same project can't be registered under the same number
    draft = po_repository.create_po(db_session, line_items=[line], project_id=project.id, vendor_id=gp_vendor.id)
    assert draft.status == POStatus.DRAFT
    draft_line = draft.line_items[0]

    with pytest.raises(ValidationError):
        po_repository.register_po_in_gp(
            db_session,
            draft.id,
            vendor_id=gp_vendor.id,
            po_number="PO-DUP-1",
            gp_company="TUBC",
            line_items=[
                {
                    "id": str(draft_line.id),
                    "hardware_category": "HINGE",
                    "product_code": "HG-1",
                    "ordered_quantity": 1,
                    "unit_cost": 1.0,
                    "classification": None,
                    "order_as": "X",
                }
            ],
        )


def test_register_requires_order_as(db_session):
    project = _make_project(db_session)
    imported_vendor = _make_vendor(db_session, "Imported")
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = list(po.line_items)
    gp_vendor = _make_vendor(db_session, "GP Vendor", gp_vendor_id="GPV1")

    with pytest.raises(ValidationError):
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            vendor_id=gp_vendor.id,
            po_number="PO0000102",
            gp_company="TUBC",
            line_items=[
                {
                    "id": str(lines[0].id),
                    "hardware_category": "HINGE",
                    "product_code": "HG-100",
                    "ordered_quantity": 1,
                    "unit_cost": 10.0,
                    "classification": None,
                    "order_as": "  ",  # blank -> rejected
                }
            ],
        )
