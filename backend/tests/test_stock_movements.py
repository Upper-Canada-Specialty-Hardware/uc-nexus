"""Pool entry/exit flows: destock, allocate, transfer (stock/movements.py).

The remediation fixes three ways these could 500: destocking below a row's deficient floor, a partial
target-location override that lands stock where nobody chose, and a return-origin row losing its
shipment_return_item_id on the transfer create path (or two different return origins silently merging).
"""

import uuid

import pytest
from sqlalchemy import select

from app.errors import NotFoundError, ValidationError
from app.models.enums import DestockSource
from app.models.inventory import InventoryLocation
from app.models.stock_item import StockItem
from app.repositories import stock as stock_repository

from .inventory_fixtures import make_il, make_project, make_return_item, make_stock_item, wh_id

# --- destock ------------------------------------------------------------------------------------


def test_destock_moves_sound_units_to_the_stock_pool(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle="A", row="1", bay="1")

    stock_row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=4,
        source=DestockSource.OVERAGE,
        reason_text="extra on site",
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
    )

    assert il.quantity == 6
    assert stock_row.quantity == 4
    # No override given: the stock row lands at the source location.
    assert (stock_row.aisle, stock_row.row, stock_row.bay) == ("A", "1", "1")


def test_destock_below_the_deficient_floor_is_refused(db_session):
    """qty 10 / deficient 4, destock 8 as OVERAGE would leave qty 2 < deficient 4 -> CHECK -> 500."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    with pytest.raises(ValidationError):
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=8,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
        )


def test_destock_down_to_exactly_the_deficient_floor_is_allowed(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=6,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
    )

    assert il.quantity == 4
    assert il.deficient_quantity == 4  # untouched: OVERAGE moves sound units only


def test_deficient_swap_may_take_up_to_the_deficient_count(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=3)

    stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=3,
        source=DestockSource.DEFICIENT_SWAP,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
    )

    assert il.quantity == 7
    assert il.deficient_quantity == 0  # the deficient units are the ones that left


def test_deficient_swap_beyond_the_deficient_count_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=3)

    with pytest.raises(ValidationError):
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=4,  # > deficient 3
            source=DestockSource.DEFICIENT_SWAP,
            reason_text=None,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
        )


def test_full_target_override_lands_stock_at_the_chosen_location(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle="A", row="1", bay="1")

    stock_row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=5,
        source=DestockSource.CANCELLATION,
        reason_text=None,
        target_aisle="Z",
        target_row="9",
        target_bay="9",
        performed_by="warehouse",
    )

    assert (stock_row.aisle, stock_row.row, stock_row.bay) == ("Z", "9", "9")


@pytest.mark.parametrize(
    "aisle,row,bay",
    [("Z", None, None), (None, "9", None), (None, None, "9"), ("Z", "9", None)],
)
def test_partial_target_override_is_refused(db_session, aisle, row, bay):
    """Overriding only part of aisle/row/bay would keep the source's other fields - a location
    nobody chose. All three or none."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10)

    with pytest.raises(ValidationError):
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=il.id,
            quantity=5,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=aisle,
            target_row=row,
            target_bay=bay,
            performed_by="warehouse",
        )


def test_destock_of_a_return_origin_row_does_not_crash(db_session):
    project = make_project(db_session)
    ret = make_return_item(db_session, project)
    il = make_il(db_session, project, quantity=5, shipment_return_item_id=ret.id, aisle="A", row="1", bay="1")

    stock_row = stock_repository.destock_inventory(
        db_session,
        inventory_location_id=il.id,
        quantity=2,
        source=DestockSource.OVERAGE,
        reason_text=None,
        target_aisle=None,
        target_row=None,
        target_bay=None,
        performed_by="warehouse",
    )

    assert il.quantity == 3
    assert stock_row.quantity == 2


def test_destock_missing_row_raises_not_found(db_session):
    with pytest.raises(NotFoundError):
        stock_repository.destock_inventory(
            db_session,
            inventory_location_id=uuid.uuid4(),
            quantity=1,
            source=DestockSource.OVERAGE,
            reason_text=None,
            target_aisle=None,
            target_row=None,
            target_bay=None,
            performed_by="warehouse",
        )


# --- allocate -----------------------------------------------------------------------------------


def test_allocate_creates_a_stock_origin_inventory_row(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10)

    new_il = stock_repository.allocate_stock_to_project(
        db_session,
        stock_item_id=si.id,
        project_id=project.id,
        target_hardware_category="HINGE",
        target_product_code="HG-100",
        quantity=4,
        target_aisle="B",
        target_row="2",
        target_bay="2",
        performed_by="warehouse",
    )

    assert si.quantity == 6
    assert new_il.quantity == 4
    assert new_il.stock_item_id == si.id
    assert new_il.po_line_item_id is None and new_il.shipment_return_item_id is None
    assert new_il.warehouse_id == si.warehouse_id


def test_allocate_beyond_available_is_refused(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=10, deficient=3)  # available = 7

    with pytest.raises(ValidationError):
        stock_repository.allocate_stock_to_project(
            db_session,
            stock_item_id=si.id,
            project_id=project.id,
            target_hardware_category="HINGE",
            target_product_code="HG-100",
            quantity=8,
            target_aisle="B",
            target_row="2",
            target_bay="2",
            performed_by="warehouse",
        )


def test_allocate_keeps_the_drained_stock_row_for_origin_integrity(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=4)

    stock_repository.allocate_stock_to_project(
        db_session,
        stock_item_id=si.id,
        project_id=project.id,
        target_hardware_category="HINGE",
        target_product_code="HG-100",
        quantity=4,
        target_aisle="B",
        target_row="2",
        target_bay="2",
        performed_by="warehouse",
    )

    assert si.quantity == 0
    assert db_session.get(StockItem, si.id) is not None  # kept as the origin of the allocated row


# --- transfer -----------------------------------------------------------------------------------


def _dest_rows(session, project_id, aisle, row, bay):
    return list(
        session.scalars(
            select(InventoryLocation).where(
                InventoryLocation.project_id == project_id,
                InventoryLocation.aisle == aisle,
                InventoryLocation.row == row,
                InventoryLocation.bay == bay,
            )
        ).all()
    )


def test_transfer_inventory_location_creates_destination_row(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle="A", row="1", bay="1")

    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=il.id,
        quantity=4,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    assert il.quantity == 6
    dest = _dest_rows(db_session, project.id, "B", "2", "2")
    assert len(dest) == 1
    assert dest[0].quantity == 4
    assert dest[0].stock_item_id == il.stock_item_id  # origin cloned


def test_transfer_merges_into_a_matching_destination_row(db_session):
    project = make_project(db_session)
    si = make_stock_item(db_session, quantity=20)
    src = make_il(db_session, project, quantity=10, stock_item_id=si.id, aisle="A", row="1", bay="1")
    existing = make_il(db_session, project, quantity=3, stock_item_id=si.id, aisle="B", row="2", bay="2")

    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=src.id,
        quantity=4,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    assert src.quantity == 6
    assert existing.quantity == 7  # merged, not a new row
    assert len(_dest_rows(db_session, project.id, "B", "2", "2")) == 1


def test_transfer_does_not_merge_two_different_return_origins(db_session):
    """Both rows carry only shipment_return_item_id (the other three origin FKs null), so before the
    fix they matched on location alone and merged. Different return items are different provenance."""
    project = make_project(db_session)
    r1 = make_return_item(db_session, project)
    r2 = make_return_item(db_session, project)
    src = make_il(db_session, project, quantity=10, shipment_return_item_id=r1.id, aisle="A", row="1", bay="1")
    other = make_il(db_session, project, quantity=3, shipment_return_item_id=r2.id, aisle="B", row="2", bay="2")

    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=src.id,
        quantity=4,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    assert other.quantity == 3  # untouched: not the same origin
    dest = _dest_rows(db_session, project.id, "B", "2", "2")
    assert len(dest) == 2
    new_row = next(r for r in dest if r.id != other.id)
    assert new_row.quantity == 4
    assert new_row.shipment_return_item_id == r1.id


def test_transfer_return_origin_create_path_keeps_the_return_fk(db_session):
    """The create path used to copy po/receive/stock but not shipment_return_item_id, so a
    return-origin row transferred to a fresh location tripped the has-origin CHECK."""
    project = make_project(db_session)
    ret = make_return_item(db_session, project)
    src = make_il(db_session, project, quantity=8, shipment_return_item_id=ret.id, aisle="A", row="1", bay="1")

    stock_repository.transfer_inventory(
        db_session,
        source_type="INVENTORY_LOCATION",
        source_id=src.id,
        quantity=5,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="C",
        dest_row="3",
        dest_bay="3",
        performed_by="warehouse",
    )

    dest = _dest_rows(db_session, project.id, "C", "3", "3")
    assert len(dest) == 1
    assert dest[0].shipment_return_item_id == ret.id
    assert dest[0].po_line_item_id is None
    assert dest[0].receive_line_item_id is None
    assert dest[0].stock_item_id is None


def test_transfer_stock_item_source_moves_between_locations(db_session):
    si = make_stock_item(db_session, quantity=10, aisle="A", row="1", bay="1")

    stock_repository.transfer_inventory(
        db_session,
        source_type="STOCK_ITEM",
        source_id=si.id,
        quantity=4,
        dest_warehouse_id=wh_id(db_session),
        dest_aisle="B",
        dest_row="2",
        dest_bay="2",
        performed_by="warehouse",
    )

    assert si.quantity == 6
    dest = list(
        db_session.scalars(
            select(StockItem).where(
                StockItem.aisle == "B", StockItem.row == "2", StockItem.bay == "2", StockItem.product_code == "HG-100"
            )
        ).all()
    )
    assert len(dest) == 1
    assert dest[0].quantity == 4


def test_transfer_stock_item_beyond_available_is_refused(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4, aisle="A", row="1", bay="1")  # available 6

    with pytest.raises(ValidationError):
        stock_repository.transfer_inventory(
            db_session,
            source_type="STOCK_ITEM",
            source_id=si.id,
            quantity=7,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="B",
            dest_row="2",
            dest_bay="2",
            performed_by="warehouse",
        )


def test_transfer_to_the_same_location_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle="A", row="1", bay="1")

    with pytest.raises(ValidationError):
        stock_repository.transfer_inventory(
            db_session,
            source_type="INVENTORY_LOCATION",
            source_id=il.id,
            quantity=4,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="A",
            dest_row="1",
            dest_bay="1",
            performed_by="warehouse",
        )


def test_transfer_rejects_unknown_source_type(db_session):
    with pytest.raises(ValidationError):
        stock_repository.transfer_inventory(
            db_session,
            source_type="NONSENSE",
            source_id=uuid.uuid4(),
            quantity=1,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="B",
            dest_row="2",
            dest_bay="2",
            performed_by="warehouse",
        )


def test_transfer_missing_destination_fields_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle="A", row="1", bay="1")

    with pytest.raises(ValidationError):
        stock_repository.transfer_inventory(
            db_session,
            source_type="INVENTORY_LOCATION",
            source_id=il.id,
            quantity=4,
            dest_warehouse_id=wh_id(db_session),
            dest_aisle="B",
            dest_row="",
            dest_bay="2",
            performed_by="warehouse",
        )
