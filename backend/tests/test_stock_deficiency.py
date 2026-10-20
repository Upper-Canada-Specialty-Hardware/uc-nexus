"""Deficiency reporting and resolution (stock/deficiency.py).

resolve_deficiency has ten branches - five resolutions across two sources. The SEND_TO_STOCK branch
on a project row is the modal's default resolution and used to 500: it created a stock row without a
warehouse_id, which is a required kw-only argument.
"""

import uuid

import pytest

from app.errors import NotFoundError, ValidationError
from app.models.enums import DeficiencyResolution, DestockCost, DestockSource
from app.models.stock_item import StockItem
from app.repositories import stock as stock_repository

from .inventory_fixtures import make_il, make_project, make_stock_item

# --- report -------------------------------------------------------------------------------------


def test_report_inventory_deficiency_raises_the_flag(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=0)

    stock_repository.report_inventory_deficiency(
        db_session, inventory_location_id=il.id, quantity=3, reason_text="scratched", performed_by="qa"
    )

    assert il.deficient_quantity == 3


def test_report_inventory_deficiency_beyond_quantity_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=5)

    with pytest.raises(ValidationError):
        stock_repository.report_inventory_deficiency(
            db_session, inventory_location_id=il.id, quantity=6, reason_text=None, performed_by="qa"
        )


def test_report_inventory_deficiency_missing_row_raises_not_found(db_session):
    with pytest.raises(NotFoundError):
        stock_repository.report_inventory_deficiency(
            db_session, inventory_location_id=uuid.uuid4(), quantity=1, reason_text=None, performed_by="qa"
        )


def test_report_stock_deficiency_raises_the_flag(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=0)

    stock_repository.report_stock_deficiency(
        db_session, stock_item_id=si.id, quantity=2, reason_text="bent", performed_by="qa"
    )

    assert si.deficient_quantity == 2


def test_report_stock_deficiency_beyond_quantity_is_refused(db_session):
    si = make_stock_item(db_session, quantity=4)

    with pytest.raises(ValidationError):
        stock_repository.report_stock_deficiency(
            db_session, stock_item_id=si.id, quantity=5, reason_text=None, performed_by="qa"
        )


# --- resolve: project (inventory_location) source -----------------------------------------------


def test_resolve_project_send_to_stock_moves_the_units_onto_a_stock_row(db_session):
    """The branch that crashed. Default resolution in the review modal."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4, aisle="A", row="1", bay="1")

    review = stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.SEND_TO_STOCK,
        quantity=4,
        reason_text="send to shelf",
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
        destock_cost=DestockCost.KEEP,
    )

    assert il.quantity == 6
    assert il.deficient_quantity == 0
    assert review.resulting_stock_item_id is not None
    stock_row = db_session.get(StockItem, review.resulting_stock_item_id)
    assert stock_row.warehouse_id == il.warehouse_id
    assert stock_row.quantity == 4
    assert stock_row.deficient_quantity == 4


def test_resolve_project_scrap_writes_off_both_counts(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.SCRAP,
        quantity=4,
        reason_text="binned",
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert il.quantity == 6
    assert il.deficient_quantity == 0


def test_resolve_project_repair_clears_only_the_flag(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.REPAIR,
        quantity=4,
        reason_text="fixed",
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert il.quantity == 10  # units stay on the row
    assert il.deficient_quantity == 0


def test_resolve_project_return_to_vendor_needs_an_rma(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    with pytest.raises(ValidationError):
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=il.id,
            stock_item_id=None,
            resolution=DeficiencyResolution.RETURN_TO_VENDOR,
            quantity=4,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
        )


def test_resolve_project_return_to_vendor_removes_the_units(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.RETURN_TO_VENDOR,
        quantity=4,
        reason_text=None,
        rma_reference="RMA-1",
        destock_source=None,
        reviewed_by="manager",
    )

    assert il.quantity == 6
    assert il.deficient_quantity == 0


def test_resolve_project_leave_as_deficient_changes_nothing(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.LEAVE_AS_DEFICIENT,
        quantity=4,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert il.quantity == 10
    assert il.deficient_quantity == 4


def test_resolve_project_send_to_stock_accepts_an_explicit_destock_source(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    review = stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.SEND_TO_STOCK,
        quantity=4,
        reason_text=None,
        rma_reference=None,
        destock_source=DestockSource.OVERAGE,
        reviewed_by="manager",
        destock_cost=DestockCost.KEEP,
    )

    assert review.resulting_stock_item_id is not None


# --- resolve: stock-pool source -----------------------------------------------------------------


def test_resolve_stock_send_to_stock_clears_the_flag_in_place(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    review = stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=None,
        stock_item_id=si.id,
        resolution=DeficiencyResolution.SEND_TO_STOCK,
        quantity=4,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert si.quantity == 10
    assert si.deficient_quantity == 0
    assert review.resulting_stock_item_id == si.id


def test_resolve_stock_scrap_writes_off_both_counts(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=None,
        stock_item_id=si.id,
        resolution=DeficiencyResolution.SCRAP,
        quantity=4,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert si.quantity == 6
    assert si.deficient_quantity == 0


def test_resolve_stock_repair_clears_only_the_flag(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=None,
        stock_item_id=si.id,
        resolution=DeficiencyResolution.REPAIR,
        quantity=4,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert si.quantity == 10
    assert si.deficient_quantity == 0


def test_resolve_stock_return_to_vendor_removes_the_units(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=None,
        stock_item_id=si.id,
        resolution=DeficiencyResolution.RETURN_TO_VENDOR,
        quantity=4,
        reason_text=None,
        rma_reference="RMA-2",
        destock_source=None,
        reviewed_by="manager",
    )

    assert si.quantity == 6
    assert si.deficient_quantity == 0


def test_resolve_stock_leave_as_deficient_changes_nothing(db_session):
    si = make_stock_item(db_session, quantity=10, deficient=4)

    stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=None,
        stock_item_id=si.id,
        resolution=DeficiencyResolution.LEAVE_AS_DEFICIENT,
        quantity=4,
        reason_text=None,
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
    )

    assert si.quantity == 10
    assert si.deficient_quantity == 4


# --- resolve: shared validation -----------------------------------------------------------------


def test_resolve_requires_exactly_one_source(db_session):
    with pytest.raises(ValidationError):
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=None,
            stock_item_id=None,
            resolution=DeficiencyResolution.SCRAP,
            quantity=1,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
        )


def test_resolve_beyond_deficient_quantity_is_refused(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=2)

    with pytest.raises(ValidationError):
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=il.id,
            stock_item_id=None,
            resolution=DeficiencyResolution.SCRAP,
            quantity=3,  # > deficient 2
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
        )


def test_resolve_requires_a_reviewer(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4)

    with pytest.raises(ValidationError):
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=il.id,
            stock_item_id=None,
            resolution=DeficiencyResolution.SCRAP,
            quantity=4,
            reason_text=None,
            rma_reference=None,
            destock_source=None,
            reviewed_by="",
        )


def test_resolve_project_send_to_stock_carries_the_unit_cost(db_session):
    """Same carry destock_inventory applies - without it a migrated unit resolved here values at 0."""
    from decimal import Decimal

    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=4, aisle="A", row="1", bay="1", unit_cost=Decimal("6"))

    review = stock_repository.resolve_deficiency(
        db_session,
        inventory_location_id=il.id,
        stock_item_id=None,
        resolution=DeficiencyResolution.SEND_TO_STOCK,
        quantity=4,
        reason_text="send to shelf",
        rma_reference=None,
        destock_source=None,
        reviewed_by="manager",
        destock_cost=DestockCost.KEEP,
    )

    stock_row = db_session.get(StockItem, review.resulting_stock_item_id)
    assert stock_row.unit_cost == Decimal("6")


def test_resolving_more_than_is_still_flagged_says_so_in_words(db_session):
    """#1553: two reviewers resolving the same units - the second was refused naming the column."""
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=2)

    with pytest.raises(ValidationError) as refused:
        stock_repository.resolve_deficiency(
            db_session,
            inventory_location_id=il.id,
            stock_item_id=None,
            resolution=DeficiencyResolution.SCRAP,
            quantity=4,
            reason_text="binned",
            rma_reference=None,
            destock_source=None,
            reviewed_by="manager",
        )

    assert str(refused.value.message) == (
        "Only 2 of these units are still flagged deficient - someone else resolved some. "
        "Reopen to see the current count."
    )


# --- purchasing is told of a return to vendor (#1393) ----------------------------------------------


def _purchasing_notices(session, project_id):
    from sqlalchemy import select

    from app.models.enums import NotificationType
    from app.models.notification import Notification
    from app.services import notification_service

    return session.scalars(
        select(Notification).where(
            Notification.project_id == project_id,
            Notification.type == NotificationType.INVENTORY_SHORTFALL,
            Notification.recipient_role == notification_service.PO_RECIPIENT_ROLE,
        )
    ).all()


def _po_line(session, project):
    from decimal import Decimal

    from app.models.enums import POStatus
    from app.models.purchase_order import POLineItem, PurchaseOrder

    po = PurchaseOrder(
        id=uuid.uuid4(),
        request_number=f"REQ-{uuid.uuid4().hex[:8]}",
        project_id=project.id,
        status=POStatus.CLOSED,
        po_number=f"PO{uuid.uuid4().hex[:6]}",
        gp_company="TUBC",
        vendor_name_snapshot="Acme",
        company="TUBC",
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        hardware_category="HINGE",
        product_code="HG-100",
        ordered_quantity=10,
        received_quantity=10,
        unit_cost=Decimal("1.00"),
        gp_line_ord=16384,
    )
    session.add(line)
    session.flush()
    return po, line


def _resolve(session, *, il=None, si=None, resolution=DeficiencyResolution.RETURN_TO_VENDOR, quantity=3):
    stock_repository.resolve_deficiency(
        session,
        inventory_location_id=il.id if il else None,
        stock_item_id=si.id if si else None,
        resolution=resolution,
        quantity=quantity,
        reason_text=None,
        rma_reference="RMA-7" if resolution == DeficiencyResolution.RETURN_TO_VENDOR else None,
        destock_source=None,
        reviewed_by="Wendy Manager",
        destock_cost=DestockCost.ZERO,
    )
    session.flush()


def test_a_return_to_vendor_tells_purchasing_the_job_is_short(db_session):
    project = make_project(db_session)
    po, line = _po_line(db_session, project)
    stock = make_stock_item(db_session, quantity=0)
    il = make_il(db_session, project, quantity=10, deficient=3, stock_item_id=stock.id, po_line_item_id=line.id)

    _resolve(db_session, il=il)

    [notice] = _purchasing_notices(db_session, project.id)
    assert notice.message == (
        f"3 units of HINGE HG-100 went back to the vendor from PO {po.po_number} (RMA RMA-7), returned by "
        "Wendy Manager. The job is 3 short - backfill or a replacement is needed. The PO still reads received."
    )
    assert line.received_quantity == 10


def test_a_return_from_a_row_with_no_po_still_tells_purchasing(db_session):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=1)

    _resolve(db_session, il=il, quantity=1)

    [notice] = _purchasing_notices(db_session, project.id)
    assert notice.message.startswith("1 unit of HINGE HG-100 went back to the vendor (RMA RMA-7)")
    assert "PO still reads" not in notice.message


@pytest.mark.parametrize(
    "resolution",
    [
        DeficiencyResolution.SEND_TO_STOCK,
        DeficiencyResolution.SCRAP,
        DeficiencyResolution.REPAIR,
        DeficiencyResolution.LEAVE_AS_DEFICIENT,
    ],
)
def test_other_resolutions_tell_purchasing_nothing(db_session, resolution):
    project = make_project(db_session)
    il = make_il(db_session, project, quantity=10, deficient=3)

    _resolve(db_session, il=il, resolution=resolution)

    assert _purchasing_notices(db_session, project.id) == []


def test_a_pool_return_raises_nothing(db_session):
    from sqlalchemy import func, select

    from app.models.notification import Notification

    before = db_session.scalar(select(func.count()).select_from(Notification))
    si = make_stock_item(db_session, quantity=10, deficient=3)

    _resolve(db_session, si=si)

    assert db_session.scalar(select(func.count()).select_from(Notification)) == before
