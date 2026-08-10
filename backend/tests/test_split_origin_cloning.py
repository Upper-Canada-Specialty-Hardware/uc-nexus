"""split_inventory_location origin cloning (warehouse/locations.py).

A split is a change of shelf, not of provenance: the remainder inherits every origin FK. This covers
the return-origin case specifically - a row whose only origin FK is shipment_return_item_id - since
that is the column the shared clone helper was added to carry through every derived-row path.
"""

from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import make_il, make_project, make_return_item


def test_split_clones_the_return_origin_onto_the_remainder(db_session):
    project = make_project(db_session)
    ret = make_return_item(db_session, project)
    il = make_il(db_session, project, quantity=10, shipment_return_item_id=ret.id, aisle="A", row="1", bay="1")

    kept, remainder = warehouse_repository.split_inventory_location(db_session, il.id, 4, performed_by="picker")
    db_session.flush()

    assert kept.id == il.id
    assert kept.quantity == 6
    assert remainder.quantity == 4
    assert remainder.shipment_return_item_id == ret.id
    assert remainder.po_line_item_id is None
    assert remainder.receive_line_item_id is None
    assert remainder.stock_item_id is None
    assert remainder.warehouse_id == il.warehouse_id
    # The remainder is what the caller then puts away, so it starts unlocated.
    assert (remainder.aisle, remainder.row, remainder.bay) == (None, None, None)


def test_split_clones_a_stock_origin_onto_the_remainder(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, aisle="A", row="1", bay="1")

    _kept, remainder = warehouse_repository.split_inventory_location(db_session, il.id, 3, performed_by="picker")
    db_session.flush()

    assert remainder.stock_item_id == il.stock_item_id
    assert remainder.shipment_return_item_id is None
