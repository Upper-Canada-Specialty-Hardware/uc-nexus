"""The defined-locations registry and the writes it gates (#632).

Put-away used to invent a location out of free text, so the set of places hardware could be was
whatever anybody had ever typed - "A1" and "a 1" and "A-1" all being different shelves nobody could
reconcile. warehouse_locations is now the list of places that exist, and every write that lands
hardware where a USER CHOSE validates against it.

Two things are deliberately NOT checked, and both are pinned below:
  - a location a row already sits on. destock without an explicit target inherits the source shelf,
    so retiring a location can never strand the hardware standing on it.
  - the legacy put-away locations recorded inside a receive. Receiving is GP-first and the units are
    physically on the dock; refusing the Nexus half over a shelf name would split the two systems.

DB-backed like the rest of the warehouse suites: every test runs against a real Postgres in a
rolled-back transaction.
"""

import uuid

import pytest

from app.errors import ConflictError, NotFoundError, ValidationError
from app.models.enums import DestockSource
from app.repositories import stock as stock_repository
from app.repositories import warehouse as warehouse_repository
from app.repositories import warehouse_admin_repository

from .inventory_fixtures import define_location, make_il, make_project, make_stock_item, wh_id


def _second_warehouse(session) -> uuid.UUID:
    wh = warehouse_admin_repository.create_warehouse(
        session,
        name=f"WH-{uuid.uuid4().hex[:8]}",
        code=f"C{uuid.uuid4().hex[:6]}",
        is_primary=False,
    )
    session.flush()
    return wh.id


def _aisle() -> str:
    """A location string no other test in the suite is using."""
    return f"REG{uuid.uuid4().hex[:6].upper()}"


# --- the registry itself ------------------------------------------------------------------------


def test_defining_a_location_stores_it_canonical(db_session):
    """Stored uppercase, trimmed and whitespace-collapsed, so the lookup a write does against
    normalized input is exact string equality rather than a fuzzy match."""
    wh = wh_id(db_session)
    aisle = _aisle()

    loc = warehouse_repository.create_warehouse_location(db_session, wh, f"  {aisle.lower()} ", "r  7", "b9")

    assert (loc.aisle, loc.row, loc.bay) == (aisle, "R 7", "B9")
    assert loc.active is True


def test_defining_the_same_location_twice_is_a_conflict(db_session):
    wh = wh_id(db_session)
    aisle = _aisle()
    warehouse_repository.create_warehouse_location(db_session, wh, aisle, "R1", "B1")

    with pytest.raises(ConflictError):
        warehouse_repository.create_warehouse_location(db_session, wh, aisle.lower(), "r1", "b1")


def test_redefining_a_deactivated_location_reactivates_the_same_row(db_session):
    """The row keeps its identity: re-defining a retired shelf brings that shelf back rather than
    minting a second row for the same physical place."""
    wh = wh_id(db_session)
    aisle = _aisle()
    original = warehouse_repository.create_warehouse_location(db_session, wh, aisle, "R1", "B1")
    warehouse_repository.deactivate_warehouse_location(db_session, original.id)
    assert original.active is False

    again = warehouse_repository.create_warehouse_location(db_session, wh, aisle, "R1", "B1")

    assert again.id == original.id
    assert again.active is True


def test_the_same_string_in_two_warehouses_is_two_locations(db_session):
    """A location string names one physical place only WITHIN a warehouse."""
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    aisle = _aisle()

    a = warehouse_repository.create_warehouse_location(db_session, wh_a, aisle, "R1", "B1")
    b = warehouse_repository.create_warehouse_location(db_session, wh_b, aisle, "R1", "B1")

    assert a.id != b.id


def test_defining_a_location_in_a_warehouse_that_does_not_exist_is_not_found(db_session):
    with pytest.raises(NotFoundError):
        warehouse_repository.create_warehouse_location(db_session, uuid.uuid4(), "A", "1", "1")


@pytest.mark.parametrize("field,value", [("aisle", "   "), ("row", ""), ("bay", "X" * 21)])
def test_an_empty_or_over_long_field_is_a_named_validation_error(db_session, field, value):
    wh = wh_id(db_session)
    triple = {"aisle": _aisle(), "row": "R1", "bay": "B1"}
    triple[field] = value

    with pytest.raises(ValidationError) as excinfo:
        warehouse_repository.create_warehouse_location(db_session, wh, **triple)

    assert excinfo.value.field == field


def test_deactivating_a_location_that_does_not_exist_is_not_found(db_session):
    with pytest.raises(NotFoundError):
        warehouse_repository.deactivate_warehouse_location(db_session, uuid.uuid4())


def test_the_registry_read_scopes_by_warehouse_and_can_hide_retired_rows(db_session):
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    aisle = _aisle()
    live = warehouse_repository.create_warehouse_location(db_session, wh_a, aisle, "R1", "B1")
    retired = warehouse_repository.create_warehouse_location(db_session, wh_a, aisle, "R2", "B2")
    warehouse_repository.deactivate_warehouse_location(db_session, retired.id)
    elsewhere = warehouse_repository.create_warehouse_location(db_session, wh_b, aisle, "R3", "B3")

    all_in_a = {loc.id for loc in warehouse_repository.get_warehouse_locations(db_session, wh_a)}
    assert {live.id, retired.id} <= all_in_a
    assert elsewhere.id not in all_in_a

    active_in_a = {loc.id for loc in warehouse_repository.get_warehouse_locations(db_session, wh_a, active_only=True)}
    assert live.id in active_in_a
    assert retired.id not in active_in_a


def test_ensure_registered_location_accepts_active_and_refuses_the_rest(db_session):
    wh = wh_id(db_session)
    aisle = _aisle()
    loc = warehouse_repository.create_warehouse_location(db_session, wh, aisle, "R1", "B1")

    warehouse_repository.ensure_registered_location(db_session, wh, aisle, "R1", "B1")

    with pytest.raises(ValidationError) as undefined:
        warehouse_repository.ensure_registered_location(db_session, wh, aisle, "R1", "B2")
    assert undefined.value.field == "location"

    warehouse_repository.deactivate_warehouse_location(db_session, loc.id)
    with pytest.raises(ValidationError):
        warehouse_repository.ensure_registered_location(db_session, wh, aisle, "R1", "B1")


def test_a_location_defined_in_another_warehouse_does_not_count(db_session):
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    aisle = _aisle()
    warehouse_repository.create_warehouse_location(db_session, wh_b, aisle, "R1", "B1")

    with pytest.raises(ValidationError):
        warehouse_repository.ensure_registered_location(db_session, wh_a, aisle, "R1", "B1")


# --- project inventory: put-away, move, merge ---------------------------------------------------


def test_put_away_to_an_undefined_location_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, aisle=None, row=None, bay=None)

    with pytest.raises(ValidationError) as excinfo:
        warehouse_repository.assign_inventory_location(db_session, il.id, _aisle(), "R1", "B1", performed_by="wh")

    assert excinfo.value.field == "location"
    assert "not a defined location" in excinfo.value.message
    assert il.aisle is None, "nothing moved"


def test_put_away_to_a_defined_location_lands_and_normalizes_to_it(db_session):
    """The registry row is canonical, and so is the write - so a picker typing lowercase still
    matches the shelf that was defined in uppercase."""
    project = make_project(db_session)
    il = make_il(db_session, project, aisle=None, row=None, bay=None)
    aisle = _aisle()
    define_location(db_session, il.warehouse_id, aisle, "R1", "B1")

    warehouse_repository.assign_inventory_location(
        db_session, il.id, f" {aisle.lower()} ", "r1", "b1", performed_by="wh"
    )

    assert (il.aisle, il.row, il.bay) == (aisle, "R1", "B1")


def test_put_away_to_a_retired_location_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, aisle=None, row=None, bay=None)
    aisle = _aisle()
    define_location(db_session, il.warehouse_id, aisle, "R1", "B1", active=False)

    with pytest.raises(ValidationError):
        warehouse_repository.assign_inventory_location(db_session, il.id, aisle, "R1", "B1", performed_by="wh")


def test_moving_inventory_to_an_undefined_location_is_refused(db_session):
    project = make_project(db_session)
    aisle = _aisle()
    define_location(db_session, None, aisle, "R1", "B1")
    il = make_il(db_session, project, aisle=aisle, row="R1", bay="B1")

    with pytest.raises(ValidationError):
        warehouse_repository.move_inventory_location(db_session, il.id, aisle, "R2", "B2", performed_by="wh")

    define_location(db_session, il.warehouse_id, aisle, "R2", "B2")
    warehouse_repository.move_inventory_location(db_session, il.id, aisle, "R2", "B2", performed_by="wh")
    assert (il.aisle, il.row, il.bay) == (aisle, "R2", "B2")


def test_unlocating_needs_no_registry_row(db_session):
    """Clearing a shelf assignment targets no location at all, so there is nothing to validate - and
    a retired location must still be emptiable."""
    project = make_project(db_session)
    aisle = _aisle()
    loc = define_location(db_session, None, aisle, "R1", "B1")
    il = make_il(db_session, project, aisle=aisle, row="R1", bay="B1")
    warehouse_repository.deactivate_warehouse_location(db_session, loc.id)

    warehouse_repository.mark_inventory_unlocated(db_session, il.id, performed_by="wh")

    assert (il.aisle, il.row, il.bay) == (None, None, None)


def test_a_merge_target_must_be_defined(db_session):
    """The merge's SOURCE is whatever bad string is being cleaned up, so only the target is checked -
    requiring the source to be defined would make the duplicate cleanup impossible to run."""
    wh = wh_id(db_session)
    project = make_project(db_session)
    source, target = _aisle(), _aisle()
    make_il(db_session, project, aisle=source, row="R1", bay="B1", warehouse_id=wh)

    with pytest.raises(ValidationError):
        warehouse_repository.merge_locations(
            db_session,
            warehouse_id=wh,
            from_aisle=source,
            from_row="R1",
            from_bay="B1",
            to_aisle=target,
            to_row="R2",
            to_bay="B2",
            performed_by="admin",
        )

    define_location(db_session, wh, target, "R2", "B2")
    counts = warehouse_repository.merge_locations(
        db_session,
        warehouse_id=wh,
        from_aisle=source,
        from_row="R1",
        from_bay="B1",
        to_aisle=target,
        to_row="R2",
        to_bay="B2",
        performed_by="admin",
    )
    assert counts["inventory_locations"] == 1


# --- stock pool: put-away, move -----------------------------------------------------------------


def test_stock_put_away_to_an_undefined_location_is_refused(db_session):
    si = make_stock_item(db_session, quantity=5)

    with pytest.raises(ValidationError) as excinfo:
        stock_repository.assign_stock_item_location(
            db_session, stock_item_id=si.id, aisle=_aisle(), row="R1", bay="B1", performed_by="wh"
        )

    assert excinfo.value.field == "location"


def test_stock_put_away_to_a_defined_location_lands(db_session):
    si = make_stock_item(db_session, quantity=5)
    aisle = _aisle()
    define_location(db_session, si.warehouse_id, aisle, "R1", "B1")

    stock_repository.assign_stock_item_location(
        db_session, stock_item_id=si.id, aisle=aisle.lower(), row="r1", bay="b1", performed_by="wh"
    )

    assert (si.aisle, si.row, si.bay) == (aisle, "R1", "B1")


def test_moving_a_stock_row_to_an_undefined_location_is_refused(db_session):
    aisle = _aisle()
    define_location(db_session, None, aisle, "R1", "B1")
    si = make_stock_item(db_session, quantity=5, aisle=aisle, row="R1", bay="B1")

    with pytest.raises(ValidationError):
        stock_repository.move_stock_location(
            db_session, stock_item_id=si.id, new_aisle=aisle, new_row="R2", new_bay="B2", performed_by="wh"
        )

    define_location(db_session, si.warehouse_id, aisle, "R2", "B2")
    stock_repository.move_stock_location(
        db_session, stock_item_id=si.id, new_aisle=aisle, new_row="R2", new_bay="B2", performed_by="wh"
    )
    assert (si.aisle, si.row, si.bay) == (aisle, "R2", "B2")


# --- destock ------------------------------------------------------------------------------------


def test_a_destock_override_must_be_a_defined_location(db_session):
    project = make_project(db_session)
    source, target = _aisle(), _aisle()
    define_location(db_session, None, source, "R1", "B1")
    il = make_il(db_session, project, quantity=10, aisle=source, row="R1", bay="B1")

    with pytest.raises(ValidationError) as excinfo:
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=2,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=target,
            target_row="R9",
            target_bay="B9",
            performed_by="wh",
        )

    assert excinfo.value.field == "location"
    assert il.quantity == 10, "nothing moved"

    define_location(db_session, il.warehouse_id, target, "R9", "B9")
    stock_row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=2,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=target.lower(),
        target_row="r9",
        target_bay="b9",
        performed_by="wh",
    )
    assert (stock_row.aisle, stock_row.row, stock_row.bay) == (target, "R9", "B9")


def test_a_destock_inheriting_the_source_shelf_is_not_checked(db_session):
    """The deliberate hole. Nobody chose this location - the units are already standing on it - so
    retiring it (or never having defined it, as every pre-registry row is) must not block moving the
    hardware into the pool."""
    project = make_project(db_session)
    aisle = _aisle()
    il = make_il(db_session, project, quantity=10, aisle=aisle, row="R1", bay="B1")

    stock_row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=4,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="wh",
    )

    assert il.quantity == 6
    assert (stock_row.aisle, stock_row.row, stock_row.bay) == (aisle, "R1", "B1")


def test_a_destock_override_onto_a_retired_location_is_refused(db_session):
    project = make_project(db_session)
    target = _aisle()
    define_location(db_session, None, target, "R9", "B9", active=False)
    il = make_il(db_session, project, quantity=10, aisle=None, row=None, bay=None)

    with pytest.raises(ValidationError):
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=2,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=target,
            target_row="R9",
            target_bay="B9",
            performed_by="wh",
        )


# --- allocate -----------------------------------------------------------------------------------


def test_an_allocate_target_must_be_a_defined_location(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)
    target = _aisle()

    with pytest.raises(ValidationError) as excinfo:
        stock_repository.allocate_stock_to_project(
            db_session,
            stock_item_id=si.id,
            project_id=project.id,
            target_hardware_category="HINGE",
            target_product_code="HG-100",
            quantity=4,
            target_aisle=target,
            target_row="R1",
            target_bay="B1",
            performed_by="wh",
        )

    assert excinfo.value.field == "location"
    assert si.quantity == 10, "nothing moved"

    define_location(db_session, si.warehouse_id, target, "R1", "B1")
    new_il = stock_repository.allocate_stock_to_project(
        db_session,
        stock_item_id=si.id,
        project_id=project.id,
        target_hardware_category="HINGE",
        target_product_code="HG-100",
        quantity=4,
        target_aisle=target.lower(),
        target_row="r1",
        target_bay="b1",
        performed_by="wh",
    )
    assert (new_il.aisle, new_il.row, new_il.bay) == (target, "R1", "B1")


def test_an_allocate_with_no_target_lands_unlocated_and_needs_no_registry_row(db_session):
    """No target means the units go to the put-away queue, which is where a location gets chosen -
    and validated."""
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)

    new_il = stock_repository.allocate_stock_to_project(
        db_session,
        stock_item_id=si.id,
        project_id=project.id,
        target_hardware_category="HINGE",
        target_product_code="HG-100",
        quantity=4,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="wh",
    )

    assert (new_il.aisle, new_il.row, new_il.bay) == (None, None, None)


@pytest.mark.parametrize(
    "aisle,row,bay",
    [("Z", None, None), (None, "9", None), (None, None, "9"), ("Z", "9", None)],
)
def test_a_partial_allocate_target_is_refused(db_session, aisle, row, bay):
    """All-or-none, like destock's override: a partial triple lands units at a location nobody chose
    in full, and could never match a registry row anyway."""
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)

    with pytest.raises(ValidationError) as excinfo:
        stock_repository.allocate_stock_to_project(
            db_session,
            stock_item_id=si.id,
            project_id=project.id,
            target_hardware_category="HINGE",
            target_product_code="HG-100",
            quantity=4,
            target_aisle=aisle,
            target_row=row,
            target_bay=bay,
            performed_by="wh",
        )

    assert excinfo.value.field == "target_location"


# --- transfer -----------------------------------------------------------------------------------


def test_a_transfer_destination_must_be_a_defined_location(db_session):
    project = make_project(db_session)
    source, dest = _aisle(), _aisle()
    define_location(db_session, None, source, "R1", "B1")
    il = make_il(db_session, project, quantity=10, aisle=source, row="R1", bay="B1")

    with pytest.raises(ValidationError) as excinfo:
        stock_repository.transfer_inventory(
            db_session,
            source_type="INVENTORY_LOCATION",
            source_id=il.id,
            quantity=4,
            dest_warehouse_id=il.warehouse_id,
            dest_aisle=dest,
            dest_row="R2",
            dest_bay="B2",
            performed_by="wh",
        )

    assert excinfo.value.field == "location"
    assert il.quantity == 10, "nothing moved"

    define_location(db_session, il.warehouse_id, dest, "R2", "B2")
    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=il.id,
        quantity=4,
        dest_warehouse_id=il.warehouse_id,
        dest_aisle=dest,
        dest_row="R2",
        dest_bay="B2",
        performed_by="wh",
    )
    assert il.quantity == 6


def test_a_transfer_is_checked_against_the_destination_warehouse(db_session):
    """The registry is per-warehouse, so a cross-warehouse transfer has to be validated against the
    building the hardware is going to, not the one it is leaving."""
    project = make_project(db_session)
    wh_a = wh_id(db_session)
    wh_b = _second_warehouse(db_session)
    dest = _aisle()
    il = make_il(db_session, project, quantity=10, aisle=None, row=None, bay=None, warehouse_id=wh_a)
    # Defined in the SOURCE warehouse only - which must not satisfy a transfer into the other one.
    define_location(db_session, wh_a, dest, "R1", "B1")

    with pytest.raises(ValidationError):
        stock_repository.transfer_inventory(
            db_session,
            source_type="INVENTORY_LOCATION",
            source_id=il.id,
            quantity=4,
            dest_warehouse_id=wh_b,
            dest_aisle=dest,
            dest_row="R1",
            dest_bay="B1",
            performed_by="wh",
        )

    define_location(db_session, wh_b, dest, "R1", "B1")
    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=il.id,
        quantity=4,
        dest_warehouse_id=wh_b,
        dest_aisle=dest,
        dest_row="R1",
        dest_bay="B1",
        performed_by="wh",
    )
    assert il.quantity == 6
