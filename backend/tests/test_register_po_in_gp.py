"""Register an imported Draft PO into GP (issue #175): po_repository.register_po_in_gp."""

import logging
import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import HardwareItemState, POStatus
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.vendor import Vendor
from app.repositories import buyer_repository, import_repository, po_repository
from app.schemas import po as po_schema


def _assign_buyer(session, buyer_id, project):
    """Issue #216: _prepare_register_po enforces the buyer->project assignment."""
    return buyer_repository.save_assignment(session, buyer_id, [project.id])


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _make_vendor(session, name: str = "Acme") -> Vendor:
    v = Vendor(id=uuid.uuid4(), name=f"{name}-{uuid.uuid4().hex[:6]}")
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
    imported_vendor = _make_vendor(db_session, "Imported")
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = {li.product_code: li for li in po.line_items}

    gp_vendor = _make_vendor(db_session, "GP Vendor")

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
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
    assert po.gp_vendor_id == "GPV1"
    assert po.vendor_name_snapshot == "GP Vendor"
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

    gp_vendor = _make_vendor(db_session, "GP Vendor")

    po_repository.register_po_in_gp(
        db_session,
        po.id,
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
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
    gp_vendor = _make_vendor(db_session, "GP Vendor")

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
        db_session,
        po.id,
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
        vendor_id=gp_vendor.id,
        po_number="PO0000101",
        gp_company="TUBC",
        line_items=payload,
    )
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError):
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            gp_vendor_id="GPV1",
            vendor_name_snapshot="GP Vendor",
            vendor_id=gp_vendor.id,
            po_number="PO0000101",
            gp_company="TUBC",
            line_items=payload,
        )


def test_register_rejects_blank_gp_vendor_id(db_session):
    # issue #200: the GP vendor is picked live and sent explicitly - there's no local mirror to fall
    # back on, so a blank id must be rejected server-side rather than silently registering ungrounded.
    project = _make_project(db_session)
    imported_vendor = _make_vendor(db_session, "Imported")
    po = _import_draft_po(db_session, project, imported_vendor)
    lines = list(po.line_items)

    with pytest.raises(ValidationError):
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            gp_vendor_id="  ",
            vendor_name_snapshot="Imported",
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
    gp_vendor = _make_vendor(db_session, "GP Vendor")
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
        gp_vendor_id="GPV1",
        vendor_name_snapshot="GP Vendor",
    )
    # a second draft in the same project can't be registered under the same number
    draft = po_repository.create_po(db_session, line_items=[line], project_id=project.id, vendor_id=gp_vendor.id)
    assert draft.status == POStatus.DRAFT
    draft_line = draft.line_items[0]

    with pytest.raises(ValidationError):
        po_repository.register_po_in_gp(
            db_session,
            draft.id,
            gp_vendor_id="GPV1",
            vendor_name_snapshot="GP Vendor",
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
    gp_vendor = _make_vendor(db_session, "GP Vendor")

    with pytest.raises(ValidationError):
        po_repository.register_po_in_gp(
            db_session,
            po.id,
            gp_vendor_id="GPV1",
            vendor_name_snapshot="GP Vendor",
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


# --- issue #233: _prepare_register_po resolves each line's manufacturer from matching HardwareItems ----


class _NoCloseSession:
    """Wrap the test session as a context manager that does NOT close it (the db_session fixture owns its
    lifecycle), so a monkeypatched _prepare_* runs against the test's uncommitted transaction instead of a
    fresh, empty connection via the real SessionLocal()."""

    def __init__(self, session):
        self._session = session

    def __enter__(self):
        return self._session

    def __exit__(self, *exc):
        return False


def _use_test_session(monkeypatch, db_session) -> None:
    monkeypatch.setattr(po_schema, "SessionLocal", lambda: _NoCloseSession(db_session))


def _add_hardware_item(session, project, *, hardware_category, product_code, manufacturer, created_at=None):
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"OP-{uuid.uuid4().hex[:4]}")
    session.add(opening)
    session.flush()
    hi = HardwareItem(
        id=uuid.uuid4(),
        project_id=project.id,
        opening_id=opening.id,
        hardware_category=hardware_category,
        product_code=product_code,
        item_quantity=1,
        manufacturer=manufacturer,
        state=HardwareItemState.AVAILABLE,
    )
    if created_at is not None:
        hi.created_at = created_at
    session.add(hi)
    session.flush()
    return hi


def _register_line(hardware_category, product_code, order_as) -> dict:
    return {
        "id": None,
        "hardware_category": hardware_category,
        "product_code": product_code,
        "ordered_quantity": 1,
        "unit_cost": 10.0,
        "classification": None,
        "order_as": order_as,
    }


def test_prepare_register_po_attaches_manufacturer_per_line(monkeypatch, db_session):
    project = _make_project(db_session)
    _add_hardware_item(db_session, project, hardware_category="HINGE", product_code="HG-100", manufacturer="SCHLAGE")
    _add_hardware_item(db_session, project, hardware_category="LOCK", product_code="LK-200", manufacturer="SARGENT")
    gp_vendor = _make_vendor(db_session, "GP Vendor")
    draft = po_repository.create_po(
        db_session,
        line_items=[_register_line("HINGE", "HG-100", "ALIAS-100"), _register_line("LOCK", "LK-200", "ALIAS-200")],
        project_id=project.id,
        vendor_id=gp_vendor.id,
    )
    assert draft.status == POStatus.DRAFT
    _assign_buyer(db_session, "mira", project)
    _use_test_session(monkeypatch, db_session)

    payload = po_schema._prepare_register_po(
        po_id=draft.id,
        vendor_id=None,
        gp_vendor_id="GPV1",
        buyer_id="mira",
        cost_code="210-200-2",
        line_items_data=[_register_line("HINGE", "HG-100", "ALIAS-100"), _register_line("LOCK", "LK-200", "ALIAS-200")],
    )

    assert [line["manufacturer"] for line in payload["lines"]] == ["SCHLAGE", "SARGENT"]


def test_prepare_register_po_accepts_any_cost_code(monkeypatch, db_session):
    """Per-buyer cost-code designation is gone: the buyer is assigned to the project and nothing else,
    so a code that no designation would ever have listed still registers. This used to raise a
    'not designated to buyer' ValidationError on field cost_code."""
    project = _make_project(db_session)
    _add_hardware_item(db_session, project, hardware_category="HINGE", product_code="HG-100", manufacturer="SCHLAGE")
    gp_vendor = _make_vendor(db_session, "GP Vendor")
    draft = po_repository.create_po(
        db_session,
        line_items=[_register_line("HINGE", "HG-100", "ALIAS-100")],
        project_id=project.id,
        vendor_id=gp_vendor.id,
    )
    _assign_buyer(db_session, "mira", project)
    _use_test_session(monkeypatch, db_session)

    payload = po_schema._prepare_register_po(
        po_id=draft.id,
        vendor_id=None,
        gp_vendor_id="GPV1",
        buyer_id="mira",
        cost_code="900-000-9",  # 'Misc.' - never in anyone's designated list
        line_items_data=[_register_line("HINGE", "HG-100", "ALIAS-100")],
    )

    assert payload["lines"][0]["cost_code"] == "900-000-9"


def test_prepare_register_po_disagreeing_items_take_first_non_null_and_log(monkeypatch, db_session, caplog):
    project = _make_project(db_session)
    # same category + code across two openings with conflicting manufacturers; created_at is set so
    # "first non-null" is deterministic (SCHLAGE precedes SARGENT).
    _add_hardware_item(
        db_session,
        project,
        hardware_category="HINGE",
        product_code="HG-100",
        manufacturer="SCHLAGE",
        created_at=datetime(2026, 1, 1, 0, 0, 1),
    )
    _add_hardware_item(
        db_session,
        project,
        hardware_category="HINGE",
        product_code="HG-100",
        manufacturer="SARGENT",
        created_at=datetime(2026, 1, 1, 0, 0, 2),
    )
    gp_vendor = _make_vendor(db_session, "GP Vendor")
    draft = po_repository.create_po(
        db_session,
        line_items=[_register_line("HINGE", "HG-100", "ALIAS-100")],
        project_id=project.id,
        vendor_id=gp_vendor.id,
    )
    _assign_buyer(db_session, "mira", project)
    _use_test_session(monkeypatch, db_session)

    with caplog.at_level(logging.WARNING):
        payload = po_schema._prepare_register_po(
            po_id=draft.id,
            vendor_id=None,
            gp_vendor_id="GPV1",
            buyer_id="mira",
            cost_code="210-200-2",
            line_items_data=[_register_line("HINGE", "HG-100", "ALIAS-100")],
        )

    assert payload["lines"][0]["manufacturer"] == "SCHLAGE"
    assert any("manufacturer disagreement" in r.message for r in caplog.records)


# --- adopting a project at register time (#316) --------------------------------------------------------
# Project used to be locked for every registration, which left a manually created stock PO
# (create_draft_po takes an optional project_id) with no way to ever gain one - the register dialog was
# the only place the field appeared. It may now be set, but only onto a draft that has none.


def _stock_draft_po(session) -> PurchaseOrder:
    """A manually created PO with no project - the case the lock stranded. This is the same call the
    create_draft_po resolver makes (#256), which is where a stock PO comes from."""
    return po_repository.create_po(
        session,
        line_items=[
            {
                "hardware_category": "HINGE",
                "product_code": "HG-100",
                "ordered_quantity": 2,
                "unit_cost": 10.0,
                "classification": None,
                "order_as": "ALIAS-100",
            }
        ],
        project_id=None,
    )


def _register(session, po, **overrides):
    kwargs = {
        "gp_vendor_id": "GPV1",
        "vendor_name_snapshot": "GP Vendor",
        "po_number": f"PO{uuid.uuid4().hex[:8].upper()}",
        "gp_company": "TUBC",
        "line_items": [
            {
                "id": str(li.id),
                "hardware_category": li.hardware_category,
                "product_code": li.product_code,
                "ordered_quantity": li.ordered_quantity,
                "unit_cost": float(li.unit_cost),
                "classification": None,
                "order_as": li.order_as or "ALIAS",
            }
            for li in po.line_items
        ],
    }
    kwargs.update(overrides)
    return po_repository.register_po_in_gp(session, po.id, **kwargs)


def test_register_adopts_a_project_onto_a_draft_that_has_none(db_session):
    project = _make_project(db_session)
    po = _stock_draft_po(db_session)
    assert po.project_id is None

    _register(db_session, po, project_id=project.id)

    assert po_repository.reload_po(db_session, po.id).project_id == project.id


def test_register_ignores_a_project_override_on_a_po_that_already_has_one(db_session):
    # The lines were imported against the original project's hardware schedule; re-pointing the header
    # would leave them describing hardware for a different job. Enforced here, not only in the dialog,
    # so a direct GraphQL call gets the same guarantee.
    original = _make_project(db_session)
    other = _make_project(db_session)
    po = _import_draft_po(db_session, original, _make_vendor(db_session, "Imported"))

    _register(db_session, po, project_id=other.id)

    assert po_repository.reload_po(db_session, po.id).project_id == original.id


def test_register_rejects_a_project_that_does_not_exist(db_session):
    from app.errors import NotFoundError

    po = _stock_draft_po(db_session)
    with pytest.raises(NotFoundError):
        _register(db_session, po, project_id=uuid.uuid4())


def test_register_without_a_project_override_leaves_a_stock_po_unattached(db_session):
    po = _stock_draft_po(db_session)
    _register(db_session, po)
    assert po_repository.reload_po(db_session, po.id).project_id is None
