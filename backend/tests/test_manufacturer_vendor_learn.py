"""Learn-on-confirm: po_repository upserts manufacturer -> GP vendor from confirmed POs (issue #232).

The manufacturer lives on the HardwareItem, matched by project_id + hardware_category + product_code.
create_po/register_po_in_gp learn once the PO is GP-registered. A mapping-write failure is savepoint-
isolated and must never fail the PO. DB-backed - skipped when DATABASE_URL is unset."""

import uuid

from app.models.enums import HardwareItemState, POStatus
from app.models.hardware import HardwareItem
from app.models.manufacturer_vendor_map import ManufacturerVendorMap
from app.models.project import Opening, Project
from app.repositories import manufacturer_vendor_map_repository as map_repo
from app.repositories import po_repository
from app.services import manufacturer_match


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_hardware(session, project, *, category, code, manufacturer) -> HardwareItem:
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"O-{uuid.uuid4().hex[:4]}")
    session.add(opening)
    session.flush()
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=category,
        product_code=code,
        item_quantity=1,
        manufacturer=manufacturer,
        state=HardwareItemState.AVAILABLE,
    )
    session.add(hi)
    session.flush()
    return hi


def _line(category: str, code: str, order_as: str = "X") -> dict:
    return {
        "hardware_category": category,
        "product_code": code,
        "ordered_quantity": 1,
        "unit_cost": 10.0,
        "classification": None,
        "order_as": order_as,
    }


def _create_registered_po(session, project, *, gp_vendor_id="GPV1", vendor_name="Acme GP Vendor", lines=None):
    return po_repository.create_po(
        session,
        line_items=lines if lines is not None else [_line("HINGE", "HG-100")],
        project_id=project.id,
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
        gp_company="TUBC",
        gp_vendor_id=gp_vendor_id,
        vendor_name_snapshot=vendor_name,
    )


def test_create_po_learns_manufacturer_mapping(db_session):
    project = _make_project(db_session)
    _make_hardware(db_session, project, category="HINGE", code="HG-100", manufacturer="Acme Inc")

    po = _create_registered_po(db_session, project)
    assert po.status == POStatus.GP_REGISTERED

    row = map_repo.lookup(db_session, "TUBC", manufacturer_match.normalize("Acme Inc"))
    assert row is not None
    assert row.manufacturer_key == "ACME"
    assert row.gp_vendor_id == "GPV1"
    assert row.gp_vendor_name == "Acme GP Vendor"
    assert row.source == "confirmed"


def test_second_po_same_manufacturer_returns_saved_vendor(db_session):
    project = _make_project(db_session)
    _make_hardware(db_session, project, category="HINGE", code="HG-100", manufacturer="Acme Inc")
    _create_registered_po(db_session, project, gp_vendor_id="GPV1", vendor_name="Acme GP Vendor")

    # A later lookup for the same normalized manufacturer resolves to the learned vendor (the
    # suggestVendorForManufacturer saved-mapping branch reads exactly this).
    row = map_repo.lookup(db_session, "TUBC", manufacturer_match.normalize("ACME, INC."))
    assert row is not None
    assert row.gp_vendor_id == "GPV1"


def test_confirming_new_vendor_repoints_mapping(db_session):
    project = _make_project(db_session)
    _make_hardware(db_session, project, category="HINGE", code="HG-100", manufacturer="Acme Inc")

    _create_registered_po(db_session, project, gp_vendor_id="GPV1", vendor_name="Acme GP Vendor")
    _create_registered_po(db_session, project, gp_vendor_id="GPV2", vendor_name="Acme Alt Vendor")

    rows = (
        db_session.query(ManufacturerVendorMap)
        .filter(ManufacturerVendorMap.gp_company == "TUBC", ManufacturerVendorMap.manufacturer_key == "ACME")
        .all()
    )
    assert len(rows) == 1  # upsert, not a second row
    assert rows[0].gp_vendor_id == "GPV2"


def test_distinct_manufacturers_each_learned(db_session):
    project = _make_project(db_session)
    _make_hardware(db_session, project, category="HINGE", code="HG-100", manufacturer="Acme Inc")
    _make_hardware(db_session, project, category="LOCK", code="LK-200", manufacturer="Schlage Ltd")

    _create_registered_po(
        db_session,
        project,
        lines=[_line("HINGE", "HG-100"), _line("LOCK", "LK-200")],
    )

    assert map_repo.lookup(db_session, "TUBC", "ACME") is not None
    assert map_repo.lookup(db_session, "TUBC", "SCHLAGE") is not None


def test_plain_draft_does_not_learn(db_session):
    project = _make_project(db_session)
    _make_hardware(db_session, project, category="HINGE", code="HG-100", manufacturer="Acme Inc")

    # No po_number/gp_company/gp_vendor -> stays DRAFT -> nothing learned.
    draft = po_repository.create_po(db_session, line_items=[_line("HINGE", "HG-100")], project_id=project.id)
    assert draft.status == POStatus.DRAFT
    assert map_repo.lookup(db_session, "TUBC", "ACME") is None


def test_mapping_write_failure_does_not_fail_po(db_session, monkeypatch):
    project = _make_project(db_session)
    _make_hardware(db_session, project, category="HINGE", code="HG-100", manufacturer="Acme Inc")

    def boom(*args, **kwargs):
        raise RuntimeError("mapping write blew up")

    monkeypatch.setattr(map_repo, "upsert", boom)

    # The savepoint rolls back the failed mapping write and the failure is swallowed, so the PO still
    # persists as GP-registered.
    po = _create_registered_po(db_session, project)
    assert po.status == POStatus.GP_REGISTERED
    assert po.po_number is not None
    # nothing was written to the mapping table
    assert map_repo.lookup(db_session, "TUBC", "ACME") is None


def test_register_po_in_gp_learns_manufacturer_mapping(db_session):
    from sqlalchemy import select

    from app.models.purchase_order import PurchaseOrder
    from app.repositories import import_repository

    project = _make_project(db_session)
    import_repository.finalize_import_session(
        db_session,
        {
            "project_id": str(project.id),
            "openings": [
                {"opening_number": "A01", "building": None, "floor": None, "location": None},
            ],
            "hardware_items": [
                {
                    "opening_number": "A01",
                    "product_code": "HG-100",
                    "hardware_category": "HINGE",
                    "item_quantity": 1,
                    "manufacturer": "Schlage Inc",
                },
            ],
            "po_drafts": [
                {
                    "po_number": None,
                    "vendor_id": None,
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
    db_session.flush()
    po = db_session.scalars(select(PurchaseOrder).where(PurchaseOrder.project_id == project.id)).first()
    assert po is not None and po.status == POStatus.DRAFT
    line = po.line_items[0]

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        gp_vendor_id="GPV7",
        vendor_name_snapshot="Schlage GP Vendor",
        po_number=f"PO-{uuid.uuid4().hex[:8]}",
        gp_company="TUBC",
        line_items=[
            {
                "id": str(line.id),
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 1,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": "ALIAS-100",
            }
        ],
    )
    db_session.flush()

    row = map_repo.lookup(db_session, "TUBC", "SCHLAGE")
    assert row is not None
    assert row.gp_vendor_id == "GPV7"
    assert row.gp_vendor_name == "Schlage GP Vendor"
