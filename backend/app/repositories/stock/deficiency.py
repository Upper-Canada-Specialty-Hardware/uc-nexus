"""Deficiency reporting, the review queue, and resolution flows."""

import uuid
from datetime import datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import (
    AuditAction,
    AuditEntityType,
    DeficiencyResolution,
    DeficientItemSource,
    DestockSource,
)
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.stock_item import StockItem

from .common import _find_or_create_stock_row, _log_audit_event
from .items import get_stock_item


def report_inventory_deficiency(
    session: Session,
    *,
    inventory_location_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> InventoryLocationModel:
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    il = session.get(InventoryLocationModel, inventory_location_id)
    if il is None:
        raise NotFoundError(f"Inventory location {inventory_location_id} not found")

    new_deficient = (il.deficient_quantity or 0) + quantity
    if new_deficient > il.quantity:
        raise ValidationError(
            "Reported deficient quantity exceeds total quantity on row",
            field="quantity",
        )
    il.deficient_quantity = new_deficient

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newDeficientQuantity": new_deficient,
            "reasonText": reason_text,
            "hardwareCategory": il.hardware_category,
            "productCode": il.product_code,
        },
    )
    return il


def report_stock_deficiency(
    session: Session,
    *,
    stock_item_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
) -> StockItem:
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    si = get_stock_item(session, stock_item_id)
    new_deficient = (si.deficient_quantity or 0) + quantity
    if new_deficient > si.quantity:
        raise ValidationError(
            "Reported deficient quantity exceeds total quantity on row",
            field="quantity",
        )
    si.deficient_quantity = new_deficient

    _log_audit_event(
        session,
        project_id=None,
        entity_type=AuditEntityType.STOCK_ITEM,
        entity_id=si.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newDeficientQuantity": new_deficient,
            "reasonText": reason_text,
            "hardwareCategory": si.hardware_category,
            "productCode": si.product_code,
        },
    )
    return si


def report_deficiency_at_assembly(
    session: Session,
    *,
    sa_opening_item_id: uuid.UUID,
    quantity: int,
    reason_text: str | None,
    performed_by: str,
):
    """A checklist item was flagged deficient at assembly completion (#225).

    Returns the deficient unit(s) to project inventory flagged deficient (quantity AND
    deficient_quantity both bumped on an existing InventoryLocation row for the same
    project/category/product) AND auto-creates a replacement pull request item so the
    shortfall flows back through the pull gates.

    Both counts move together, so the row never violates deficient_quantity <= quantity;
    available (= quantity - deficient) is unchanged, so the returned unit can't be re-pulled.

    The replacement pull request is derived from the opening's shop-assembly PullRequest
    (#222 re-parenting); the retired SAR link is only a fallback for legacy rows.

    Returns (inventory_location, replacement_pull_request_item).
    """
    from app.models.enums import PullRequestItemType, PullRequestSource, PullRequestStatus
    from app.models.pull_request import PullRequest as PullRequestModel
    from app.models.pull_request import PullRequestItem as PullRequestItemModel
    from app.models.shop_assembly import ShopAssemblyOpening as SAOpeningModel
    from app.models.shop_assembly import ShopAssemblyOpeningItem as SAOpeningItemModel

    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")

    sa_oi = session.get(SAOpeningItemModel, sa_opening_item_id)
    if sa_oi is None:
        raise NotFoundError(f"Shop assembly opening item {sa_opening_item_id} not found")

    sa_opening = session.get(SAOpeningModel, sa_oi.shop_assembly_opening_id)
    if sa_opening is None:
        raise NotFoundError(f"Shop assembly opening {sa_oi.shop_assembly_opening_id} not found")

    # Learn project + replacement PR number from the shop-assembly PullRequest the opening
    # hangs off (#222). Fall back to the legacy SAR link only for pre-#222 rows.
    source_pr = session.get(PullRequestModel, sa_opening.pull_request_id) if sa_opening.pull_request_id else None
    if source_pr is not None:
        project_id = source_pr.project_id
        replacement_basis = source_pr.request_number
    elif sa_opening.shop_assembly_request is not None:
        project_id = sa_opening.shop_assembly_request.project_id
        replacement_basis = sa_opening.shop_assembly_request.request_number
    else:
        raise NotFoundError(f"Shop assembly opening {sa_opening.id} is not linked to a pull request")

    # Resolve an existing project inventory row for this category/product to return the
    # deficient unit onto. A row persists even at quantity 0 after a pull (never deleted),
    # so the pulled-then-deficient unit has somewhere to land.
    il_stmt = (
        select(InventoryLocationModel)
        .where(
            InventoryLocationModel.project_id == project_id,
            InventoryLocationModel.hardware_category == sa_oi.hardware_category,
            InventoryLocationModel.product_code == sa_oi.product_code,
        )
        .order_by(InventoryLocationModel.received_at.desc())
    )
    il = session.scalars(il_stmt).first()
    if il is None:
        # Row was hard-deleted (e.g. replace-schedule re-upload) after the unit was pulled.
        # Re-materialize a project inventory row so the returned deficient unit has somewhere to
        # land. Origin is a stock row (find-or-create) to satisfy ck_inventory_locations_has_origin;
        # no stock quantity is decremented - this unit came from the project's own deleted inventory.
        from app.repositories import warehouse_admin_repository

        now = datetime.utcnow()
        warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
        stock_row = _find_or_create_stock_row(
            session,
            warehouse_id=warehouse_id,
            hardware_category=sa_oi.hardware_category,
            product_code=sa_oi.product_code,
            aisle=None,
            row=None,
            bay=None,
            received_at=now,
        )
        il = InventoryLocationModel(
            project_id=project_id,
            stock_item_id=stock_row.id,
            warehouse_id=warehouse_id,
            hardware_category=sa_oi.hardware_category,
            product_code=sa_oi.product_code,
            quantity=0,
            deficient_quantity=0,
            received_at=now,
        )
        session.add(il)
        session.flush()  # populate il.id for the audit log's entity_id

    il.quantity += quantity
    il.deficient_quantity = (il.deficient_quantity or 0) + quantity

    _log_audit_event(
        session,
        project_id=il.project_id,
        entity_type=AuditEntityType.INVENTORY_LOCATION,
        entity_id=il.id,
        action=AuditAction.REPORT_DEFICIENT,
        performed_by=performed_by,
        detail={
            "quantity": quantity,
            "newQuantity": il.quantity,
            "newDeficientQuantity": il.deficient_quantity,
            "reasonText": reason_text,
            "hardwareCategory": il.hardware_category,
            "productCode": il.product_code,
            "context": "assembly_completion",
            "shopAssemblyOpeningItemId": str(sa_oi.id),
        },
    )

    # Find or create an open replacement pull request for this opening's shop-assembly PR.
    replacement_request_number = f"PR-REPL-{replacement_basis}"
    existing_pr_stmt = select(PullRequestModel).where(
        PullRequestModel.request_number == replacement_request_number,
        PullRequestModel.deleted_at.is_(None),
        PullRequestModel.status.in_([PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS]),
    )
    existing_pr = session.scalars(existing_pr_stmt).first()
    if existing_pr is None:
        replacement_pr = PullRequestModel(
            request_number=replacement_request_number,
            project_id=il.project_id,
            source=PullRequestSource.SHOP_ASSEMBLY,
            status=PullRequestStatus.PENDING,
            requested_by=performed_by,
        )
        session.add(replacement_pr)
        session.flush()
    else:
        replacement_pr = existing_pr

    opening_number = sa_opening.opening_number or "REPLACEMENT"

    pri = PullRequestItemModel(
        pull_request_id=replacement_pr.id,
        item_type=PullRequestItemType.LOOSE,
        opening_number=opening_number,
        # Restore the identity the replacement is owed to (#339). Without these the replacement was
        # a bare (opening, product) line: the warehouse could not tell a pair's leaf-1 replacement
        # from its leaf-2 one, and nothing tied the pulled unit back to the checklist item that
        # failed. leaf comes from the ShopAssemblyOpening (the assembly work unit is one leaf);
        # sa_opening_item_id is the direct link the replacement-loop closure reads.
        leaf=sa_opening.leaf,
        sa_opening_item_id=sa_oi.id,
        hardware_category=il.hardware_category,
        product_code=il.product_code,
        requested_quantity=quantity,
    )
    session.add(pri)
    session.flush()

    return (il, pri)


def resolve_deficiency(
    session: Session,
    *,
    inventory_location_id: uuid.UUID | None,
    stock_item_id: uuid.UUID | None,
    resolution: DeficiencyResolution,
    quantity: int,
    reason_text: str | None,
    rma_reference: str | None,
    destock_source: DestockSource | None,
    reviewed_by: str,
):
    """Resolve a deficient batch. Exactly one of inventory_location_id / stock_item_id is set."""
    from app.models.deficiency_review import DeficiencyReview

    if (inventory_location_id is None) == (stock_item_id is None):
        raise ValidationError(
            "Exactly one of inventory_location_id / stock_item_id must be provided",
            field="source",
        )
    if quantity < 1:
        raise ValidationError("quantity must be >= 1", field="quantity")
    if not reviewed_by:
        raise ValidationError("reviewed_by is required", field="reviewed_by")
    if resolution == DeficiencyResolution.RETURN_TO_VENDOR and not rma_reference:
        raise ValidationError(
            "rma_reference is required when resolution is RETURN_TO_VENDOR",
            field="rma_reference",
        )
    if resolution == DeficiencyResolution.SEND_TO_STOCK and destock_source is None:
        # default to DEFICIENT_SWAP for project sources if not specified
        destock_source = DestockSource.DEFICIENT_SWAP

    resulting_stock_item_id: uuid.UUID | None = None
    project_for_audit: uuid.UUID | None = None
    hardware_category: str
    product_code: str

    if inventory_location_id is not None:
        il = session.get(InventoryLocationModel, inventory_location_id)
        if il is None:
            raise NotFoundError(f"Inventory location {inventory_location_id} not found")
        if quantity > (il.deficient_quantity or 0):
            raise ValidationError(
                "Resolved quantity exceeds current deficient_quantity",
                field="quantity",
            )
        project_for_audit = il.project_id
        hardware_category = il.hardware_category
        product_code = il.product_code

        if resolution == DeficiencyResolution.SEND_TO_STOCK:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
            stock_row = _find_or_create_stock_row(
                session,
                hardware_category=il.hardware_category,
                product_code=il.product_code,
                aisle=il.aisle,
                row=il.row,
                bay=il.bay,
                received_at=datetime.utcnow(),
            )
            stock_row.quantity += quantity
            stock_row.deficient_quantity += quantity
            resulting_stock_item_id = stock_row.id
        elif resolution == DeficiencyResolution.SCRAP:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.REPAIR:
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.RETURN_TO_VENDOR:
            il.quantity -= quantity
            il.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.LEAVE_AS_DEFICIENT:
            pass

    else:
        si = get_stock_item(session, stock_item_id)
        if quantity > (si.deficient_quantity or 0):
            raise ValidationError(
                "Resolved quantity exceeds current deficient_quantity",
                field="quantity",
            )
        hardware_category = si.hardware_category
        product_code = si.product_code

        if resolution == DeficiencyResolution.SEND_TO_STOCK:
            # Already on stock — for parity record a re-routing into a (possibly new) row.
            # Practically, leave on the same row but clear the deficient flag
            si.deficient_quantity -= quantity
            resulting_stock_item_id = si.id
        elif resolution == DeficiencyResolution.SCRAP:
            si.quantity -= quantity
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.REPAIR:
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.RETURN_TO_VENDOR:
            si.quantity -= quantity
            si.deficient_quantity -= quantity
        elif resolution == DeficiencyResolution.LEAVE_AS_DEFICIENT:
            pass

        # Keep empty stock rows for the same reason allocate does — see comment there.

    review = DeficiencyReview(
        inventory_location_id=inventory_location_id,
        stock_item_id=stock_item_id,
        resolution=resolution,
        quantity=quantity,
        reason_text=reason_text,
        rma_reference=rma_reference,
        reviewed_by=reviewed_by,
        resulting_stock_item_id=resulting_stock_item_id,
    )
    session.add(review)
    session.flush()

    detail = {
        "resolution": resolution.value,
        "quantity": quantity,
        "reasonText": reason_text,
        "rmaReference": rma_reference,
        "destockSource": destock_source.value if destock_source else None,
        "resultingStockItemId": str(resulting_stock_item_id) if resulting_stock_item_id else None,
        "hardwareCategory": hardware_category,
        "productCode": product_code,
    }
    if inventory_location_id is not None:
        _log_audit_event(
            session,
            project_id=project_for_audit,
            entity_type=AuditEntityType.INVENTORY_LOCATION,
            entity_id=inventory_location_id,
            action=AuditAction.RESOLVE_DEFICIENT,
            performed_by=reviewed_by,
            detail=detail,
        )
    if stock_item_id is not None:
        _log_audit_event(
            session,
            project_id=None,
            entity_type=AuditEntityType.STOCK_ITEM,
            entity_id=stock_item_id,
            action=AuditAction.RESOLVE_DEFICIENT,
            performed_by=reviewed_by,
            detail=detail,
        )

    return review


def get_deficient_items(
    session: Session,
    project_id: uuid.UUID | None = None,
    source: DeficientItemSource | None = None,
) -> list[dict]:
    rows: list[dict] = []

    if source is None or source == DeficientItemSource.PROJECT_INVENTORY:
        il_stmt = select(InventoryLocationModel).where(InventoryLocationModel.deficient_quantity > 0)
        if project_id is not None:
            il_stmt = il_stmt.where(InventoryLocationModel.project_id == project_id)
        il_stmt = il_stmt.order_by(
            InventoryLocationModel.project_id,
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
        for il in session.scalars(il_stmt).all():
            rows.append(
                {
                    "source": DeficientItemSource.PROJECT_INVENTORY,
                    "inventory_location_id": il.id,
                    "stock_item_id": None,
                    "project_id": il.project_id,
                    "hardware_category": il.hardware_category,
                    "product_code": il.product_code,
                    "deficient_quantity": il.deficient_quantity,
                    "aisle": il.aisle,
                    "row": il.row,
                    "bay": il.bay,
                }
            )

    if (source is None or source == DeficientItemSource.STOCK_POOL) and project_id is None:
        si_stmt = (
            select(StockItem)
            .where(StockItem.deficient_quantity > 0)
            .order_by(StockItem.hardware_category, StockItem.product_code)
        )
        for si in session.scalars(si_stmt).all():
            rows.append(
                {
                    "source": DeficientItemSource.STOCK_POOL,
                    "inventory_location_id": None,
                    "stock_item_id": si.id,
                    "project_id": None,
                    "hardware_category": si.hardware_category,
                    "product_code": si.product_code,
                    "deficient_quantity": si.deficient_quantity,
                    "aisle": si.aisle,
                    "row": si.row,
                    "bay": si.bay,
                }
            )
    return rows


def get_deficiency_reviews(
    session: Session,
    inventory_location_id: uuid.UUID | None = None,
    stock_item_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
) -> list:
    from app.models.deficiency_review import DeficiencyReview

    stmt = select(DeficiencyReview).order_by(DeficiencyReview.reviewed_at.desc())
    if inventory_location_id is not None:
        stmt = stmt.where(DeficiencyReview.inventory_location_id == inventory_location_id)
    if stock_item_id is not None:
        stmt = stmt.where(DeficiencyReview.stock_item_id == stock_item_id)
    if project_id is not None:
        # Project-scoped reviews join through inventory_locations
        il_ids = select(InventoryLocationModel.id).where(InventoryLocationModel.project_id == project_id)
        stmt = stmt.where(
            or_(
                DeficiencyReview.inventory_location_id.in_(il_ids),
                # also include any review whose resulting stock item came from a project row
                # (covered by inventory_location_id above; pure stock-side reviews don't have a project)
            )
        )
    return list(session.scalars(stmt).all())
