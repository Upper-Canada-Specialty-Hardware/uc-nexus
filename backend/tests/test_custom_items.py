"""The catalog of non-schedule inventory - frames, specialties, consumables (#454).

Two things are being pinned here, and the second matters more than the first.

The first is the catalog's own rules: a type's code is claimed once and never changes, a code
already in play as a hardware category is refused, retiring is not deleting, and an attribute's
values survive its rename.

The second is that **the catalog changes nothing about the pipeline**. The whole design rests on a
type's code riding in the existing free-text `hardware_category`, so a frame has to be able to be
ordered, received into inventory and claimed by a shipping-out request through exactly the code paths
a hinge uses, with no branch anywhere that knows what a frame is. `test_a_frame_travels_the_hardware_pipeline`
is that claim; if it ever fails, the design has stopped being true.
"""

import uuid
from datetime import datetime

import pytest
from sqlalchemy import select

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import HardwareItemState, POStatus, ReservationSource
from app.models.hardware import HardwareItem
from app.models.inventory import InventoryLocation
from app.models.inventory_item_type import CustomInventoryItemValue, InventoryItemType
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.stock_item import StockItem
from app.repositories import custom_items_repository as catalog
from app.repositories import shipping_requests, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def _type(session, name=None, **kwargs):
    return catalog.create_item_type(session, name=name or f"Type {uuid.uuid4().hex[:6]}", **kwargs)


# --- the seeded three -------------------------------------------------------------------------


def test_the_three_types_the_issue_names_are_seeded(db_session):
    """A fresh database already knows about frames, specialties and consumables. They are the reason
    the feature exists, so a first-run screen that starts empty would be a worse default."""
    codes = {t.code for t in catalog.get_item_types(db_session)}
    assert {"FRAME", "SPECIALTY", "CONSUMABLE"} <= codes


# --- types ------------------------------------------------------------------------------------


def test_code_is_derived_from_the_name_and_is_predictable(db_session):
    created = _type(db_session, name="Door Sweeps")
    assert created.code == "DOOR_SWEEPS"


def test_an_explicit_code_is_normalized_rather_than_taken_verbatim(db_session):
    created = _type(db_session, name="Weatherstrip", code="weather strip")
    assert created.code == "WEATHER_STRIP"


def test_a_type_cannot_reuse_another_types_code(db_session):
    _type(db_session, name="Gaskets", code="GASKET")
    with pytest.raises(ConflictError):
        _type(db_session, name="Gasketry", code="GASKET")


def test_a_type_cannot_reuse_another_types_name(db_session):
    _type(db_session, name="Gaskets")
    with pytest.raises(ConflictError):
        _type(db_session, name="gaskets")


def test_a_code_already_carrying_hardware_is_refused(db_session):
    """The check that earns its keep. Hardware categories come off the TITAN schedule and are
    registered nowhere, so the only evidence HINGE is taken is that something was bought under it.
    A type created on such a code would show every hinge in the building as one of its own items."""
    po = PurchaseOrder(id=uuid.uuid4(), request_number=f"REQ-{uuid.uuid4().hex[:6]}", status=POStatus.DRAFT)
    db_session.add(po)
    db_session.flush()
    db_session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category="WIDGET",
            product_code="WD-1",
            ordered_quantity=1,
            unit_cost=1,
        )
    )
    db_session.flush()

    with pytest.raises(ConflictError):
        _type(db_session, name="Widgets", code="WIDGET")


def test_a_code_already_on_stock_is_refused(db_session):
    db_session.add(
        StockItem(
            id=uuid.uuid4(),
            warehouse_id=warehouse_admin_repository.get_primary_warehouse_id(db_session),
            hardware_category="SHIM",
            product_code="SH-1",
            quantity=5,
            deficient_quantity=0,
            received_at=datetime.utcnow(),
        )
    )
    db_session.flush()

    with pytest.raises(ConflictError):
        _type(db_session, name="Shims", code="SHIM")


def test_a_code_already_on_an_imported_schedule_is_refused(db_session):
    """The earliest place a category appears. A schedule can be imported long before anything is
    ordered against it, so checking only the downstream tables would hand out a code that the next
    PO raised off that schedule collides with."""
    project = _project(db_session)
    opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number="101")
    db_session.add(opening)
    db_session.flush()
    db_session.add(
        HardwareItem(
            id=uuid.uuid4(),
            project_id=project.id,
            opening_id=opening.id,
            hardware_category="GASKETS",
            product_code="GK-1",
            item_quantity=1,
            state=HardwareItemState.AVAILABLE,
        )
    )
    db_session.flush()

    with pytest.raises(ConflictError):
        _type(db_session, name="Gaskets X", code="GASKETS")


def test_renaming_a_type_leaves_its_code_alone(db_session):
    created = _type(db_session, name="Speciality Items", code="SPECIALITY_ITEMS")
    catalog.update_item_type(db_session, created.id, name="Specialty Items")
    reloaded = catalog.get_item_type(db_session, created.id)
    assert reloaded.name == "Specialty Items"
    assert reloaded.code == "SPECIALITY_ITEMS"


def test_retiring_a_type_hides_it_from_pickers_but_not_from_management(db_session):
    created = _type(db_session, name="Retired Kind")
    catalog.update_item_type(db_session, created.id, is_active=False)

    assert created.id not in {t.id for t in catalog.get_item_types(db_session, active_only=True)}
    assert created.id in {t.id for t in catalog.get_item_types(db_session)}


def test_a_blank_name_is_refused(db_session):
    with pytest.raises(ValidationError):
        catalog.create_item_type(db_session, name="   ")


# --- attributes -------------------------------------------------------------------------------


def test_attributes_are_scoped_to_their_own_type(db_session):
    """The issue is explicit that frames' attributes are separate from specialties'. Two types
    naming an attribute the same way is not a conflict, it is the normal case."""
    frames = _type(db_session, name="Frames A")
    specialties = _type(db_session, name="Specialties A")
    catalog.create_attribute(db_session, type_id=frames.id, name="Finish")
    catalog.create_attribute(db_session, type_id=specialties.id, name="Finish")

    assert [a.name for a in catalog.get_item_type(db_session, frames.id).attributes] == ["Finish"]
    assert [a.name for a in catalog.get_item_type(db_session, specialties.id).attributes] == ["Finish"]


def test_one_type_cannot_have_the_same_attribute_twice(db_session):
    frames = _type(db_session, name="Frames B")
    catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    with pytest.raises(ConflictError):
        catalog.create_attribute(db_session, type_id=frames.id, name="fire rating")


def test_renaming_an_attribute_carries_its_values(db_session):
    """Values are keyed by attribute id, not by name, which is the whole reason a rename is safe."""
    frames = _type(db_session, name="Frames C")
    rating = catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    item = catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-1",
        values=[{"attribute_id": rating.id, "value": "90min"}],
    )

    catalog.update_attribute(db_session, rating.id, name="Fire rating (min)")

    reloaded = catalog.get_item(db_session, item.id)
    assert [(v.attribute.name, v.value) for v in reloaded.values] == [("Fire rating (min)", "90min")]


def test_retiring_an_attribute_keeps_the_answers_already_given(db_session):
    frames = _type(db_session, name="Frames D")
    handing = catalog.create_attribute(db_session, type_id=frames.id, name="Handing")
    item = catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-2",
        values=[{"attribute_id": handing.id, "value": "LH"}],
    )

    catalog.update_attribute(db_session, handing.id, is_active=False)

    assert [v.value for v in catalog.get_item(db_session, item.id).values] == ["LH"]


# --- items ------------------------------------------------------------------------------------


def test_an_item_records_the_values_it_was_given(db_session):
    frames = _type(db_session, name="Frames E")
    rating = catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    handing = catalog.create_attribute(db_session, type_id=frames.id, name="Handing")

    item = catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-3",
        description="Hollow metal frame",
        values=[
            {"attribute_id": rating.id, "value": "90min"},
            {"attribute_id": handing.id, "value": "LH"},
        ],
    )

    reloaded = catalog.get_item(db_session, item.id)
    assert reloaded.description == "Hollow metal frame"
    assert {(v.attribute.name, v.value) for v in reloaded.values} == {("Fire Rating", "90min"), ("Handing", "LH")}


def test_an_item_may_answer_only_some_of_its_types_attributes(db_session):
    """A frame whose fire rating has not been confirmed yet is still worth having a code for."""
    frames = _type(db_session, name="Frames F")
    rating = catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    catalog.create_attribute(db_session, type_id=frames.id, name="Handing")

    item = catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-4",
        values=[{"attribute_id": rating.id, "value": "45min"}],
    )
    assert len(catalog.get_item(db_session, item.id).values) == 1


def test_a_product_code_is_unique_within_its_type_and_free_across_types(db_session):
    frames = _type(db_session, name="Frames G")
    consumables = _type(db_session, name="Consumables G")
    catalog.create_item(db_session, type_id=frames.id, product_code="X-1")

    with pytest.raises(ConflictError):
        catalog.create_item(db_session, type_id=frames.id, product_code="x-1")

    catalog.create_item(db_session, type_id=consumables.id, product_code="X-1")


def test_blanking_a_value_clears_it_rather_than_storing_an_empty_answer(db_session):
    frames = _type(db_session, name="Frames H")
    rating = catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    item = catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-5",
        values=[{"attribute_id": rating.id, "value": "90min"}],
    )

    catalog.update_item(db_session, item.id, values=[{"attribute_id": rating.id, "value": "  "}])

    assert catalog.get_item(db_session, item.id).values == []
    assert (
        db_session.scalars(select(CustomInventoryItemValue).where(CustomInventoryItemValue.item_id == item.id)).all()
        == []
    )


def test_an_update_only_touches_the_attributes_it_names(db_session):
    frames = _type(db_session, name="Frames I")
    rating = catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    handing = catalog.create_attribute(db_session, type_id=frames.id, name="Handing")
    item = catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-6",
        values=[
            {"attribute_id": rating.id, "value": "90min"},
            {"attribute_id": handing.id, "value": "LH"},
        ],
    )

    catalog.update_item(db_session, item.id, values=[{"attribute_id": handing.id, "value": "RH"}])

    assert {(v.attribute.name, v.value) for v in catalog.get_item(db_session, item.id).values} == {
        ("Fire Rating", "90min"),
        ("Handing", "RH"),
    }


def test_a_value_for_another_types_attribute_is_refused(db_session):
    """Without this the bad row would simply sit in the table: the grid renders the item's own type's
    columns, so an answer hung off a foreign attribute would never be visible to correct."""
    frames = _type(db_session, name="Frames J")
    consumables = _type(db_session, name="Consumables J")
    foreign = catalog.create_attribute(db_session, type_id=consumables.id, name="Pack Size")

    with pytest.raises(ValidationError):
        catalog.create_item(
            db_session,
            type_id=frames.id,
            product_code="FR-7",
            values=[{"attribute_id": foreign.id, "value": "10"}],
        )


def test_an_item_on_a_type_that_does_not_exist_is_refused(db_session):
    with pytest.raises(NotFoundError):
        catalog.create_item(db_session, type_id=uuid.uuid4(), product_code="NOPE")


def test_a_retired_type_takes_no_new_items_or_attributes(db_session):
    """Retiring takes a type out of every picker, so the only way to reach these with a retired one
    is a stale tab or a direct call - and both should be told no rather than quietly growing the
    catalog of something the warehouse has stopped using."""
    retired = _type(db_session, name="Retired For Items")
    catalog.update_item_type(db_session, retired.id, is_active=False)

    with pytest.raises(ConflictError):
        catalog.create_item(db_session, type_id=retired.id, product_code="RT-1")
    with pytest.raises(ConflictError):
        catalog.create_attribute(db_session, type_id=retired.id, name="Too Late")


def test_creating_an_item_with_no_values_at_all_is_allowed(db_session):
    """The `values` argument is optional on the mutation, so the repository has to accept its
    absence rather than assume a list is always handed over."""
    frames = _type(db_session, name="Frames M")
    item = catalog.create_item(db_session, type_id=frames.id, product_code="FR-NOVALS")
    assert catalog.get_item(db_session, item.id).values == []


def test_a_search_term_containing_like_metacharacters_is_taken_literally(db_session):
    """Unescaped, "%" would match everything and "_" would match any single character - so a search
    would quietly return rows the user did not ask for."""
    frames = _type(db_session, name="Frames N")
    catalog.create_item(db_session, type_id=frames.id, product_code="FR-50%-A")
    catalog.create_item(db_session, type_id=frames.id, product_code="FR-999-B")

    hits = catalog.get_items(db_session, type_id=frames.id, product_code_contains="50%")
    assert [i.product_code for i in hits] == ["FR-50%-A"]

    catalog.create_item(db_session, type_id=frames.id, product_code="FRX1")
    underscore = catalog.get_items(db_session, type_id=frames.id, product_code_contains="FR_")
    assert [i.product_code for i in underscore] == []


def test_retiring_an_item_hides_it_from_the_picker_only(db_session):
    frames = _type(db_session, name="Frames K")
    item = catalog.create_item(db_session, type_id=frames.id, product_code="FR-8")
    catalog.update_item(db_session, item.id, is_active=False)

    assert catalog.get_items(db_session, type_id=frames.id, active_only=True) == []
    assert [i.id for i in catalog.get_items(db_session, type_id=frames.id)] == [item.id]


def test_the_catalog_reports_the_pair_the_pipeline_uses(db_session):
    """`(type.code, product_code)` is the only handle anything downstream has on a catalogued item,
    so the catalog has to hand it back the way inventory spells it."""
    frames = _type(db_session, name="Frames L", code="FRAME_L")
    item = catalog.create_item(db_session, type_id=frames.id, product_code="FR-9")
    reloaded = catalog.get_item(db_session, item.id)
    assert (reloaded.item_type.code, reloaded.product_code) == ("FRAME_L", "FR-9")


# --- the claim the whole design rests on -------------------------------------------------------


def test_a_frame_travels_the_hardware_pipeline_untouched(db_session):
    """Order it, receive it, claim it - through the hinge code paths, with no branch for frames.

    The catalog entry is deliberately created and then never referenced again: everything after it
    works off the `(FRAME, FR-101)` pair alone, which is what makes the feature cost nothing
    downstream. Stock is seeded the way `test_shipping_request_composition` seeds it (a StockItem as
    the origin `ck_inventory_locations_has_origin` requires) rather than through a relay receive,
    because what is being tested is the shape of the row, not GP.
    """
    frames = db_session.scalars(select(InventoryItemType).where(InventoryItemType.code == "FRAME")).one()
    rating = catalog.create_attribute(db_session, type_id=frames.id, name="Fire Rating")
    catalog.create_item(
        db_session,
        type_id=frames.id,
        product_code="FR-101",
        values=[{"attribute_id": rating.id, "value": "90min"}],
    )

    project = _project(db_session)
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(db_session)

    # Bought: an ordinary PO line, carrying the type code as its hardware category.
    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:6]}",
        project_id=project.id,
        status=POStatus.GP_REGISTERED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TEST",
    )
    db_session.add(po)
    db_session.flush()
    db_session.add(
        POLineItem(
            id=uuid.uuid4(),
            po_id=po.id,
            hardware_category="FRAME",
            product_code="FR-101",
            ordered_quantity=4,
            unit_cost=250,
        )
    )
    db_session.flush()

    # On a shelf: an ordinary inventory row, keyed on the same pair.
    stock = StockItem(
        id=uuid.uuid4(),
        warehouse_id=warehouse_id,
        hardware_category="FRAME",
        product_code="FR-101",
        quantity=4,
        deficient_quantity=0,
        received_at=datetime.utcnow(),
    )
    db_session.add(stock)
    db_session.flush()
    db_session.add(
        InventoryLocation(
            id=uuid.uuid4(),
            project_id=project.id,
            stock_item_id=stock.id,
            warehouse_id=warehouse_id,
            hardware_category="FRAME",
            product_code="FR-101",
            quantity=4,
            deficient_quantity=0,
            received_at=datetime.utcnow(),
        )
    )
    db_session.flush()

    # Visible as stock: the inventory screens group on hardware category, so the type is a group.
    hierarchy = {
        n["hardware_category"]: n for n in warehouse_repository.get_inventory_hierarchy(db_session, project.id)
    }
    assert hierarchy["FRAME"]["total_quantity"] == 4

    # Claimed: a shipping-out request holds it as a LOOSE line and reserves it (#342), exactly as
    # it would hold a hinge.
    request = shipping_requests.create_shipping_out_requests(
        db_session,
        project.id,
        [
            {
                "request_number": f"SOR-{uuid.uuid4().hex[:6]}",
                "items": [
                    {
                        "item_type": "LOOSE",
                        "opening_number": None,
                        "hardware_category": "FRAME",
                        "product_code": "FR-101",
                        "requested_quantity": 3,
                    }
                ],
            }
        ],
        created_by="Shipper",
    )[0]

    assert warehouse_repository.get_reserved_total(db_session, ReservationSource.SHIPPING_OUT_REQUEST, request.id) == 3
