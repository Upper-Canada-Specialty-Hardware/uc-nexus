"""Manual override of a project's hardware classifications after import (#735).

A product's classification is the import's three-way choice - UCH Shop, UCH Site, By Others - stored
on two axes: hardware_items.classification (SHOP_HARDWARE / SITE_HARDWARE) for every schedule row of
the product, and a project_excluded_items row for By Others. The override writes both the same way
the import's finalize does, so nothing downstream can tell an overridden product from an imported one.

Two rules decide whether a change may happen, both from the import step (#734):

- Site hardware cannot be pulled into the shop. So a product may not LEAVE shop while a live shop
  assembly request holds it - a waiting opening on a pending request, or an active batch whose pull
  has not finished - or that request would be left holding site hardware.
- By Others is not UC Hardware's to order or ship. So a product may not BECOME By Others while any of
  its schedule rows is on a PO, or while a pending shipping request asks for it.

Shop hardware can still ship out directly, so Site to Shop and By Others back into scope are always
allowed. Every change is logged in hardware_classification_changes.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from app.errors import ConflictError, ValidationError
from app.models.enums import (
    Classification,
    HardwareClassificationChoice,
    HardwareItemState,
    PullRequestStatus,
    ShippingOutRequestStatus,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.hardware_classification_change import HardwareClassificationChange
from app.models.project_excluded_item import ProjectExcludedItem
from app.models.pull_request import PullRequest
from app.models.shipping_out_request import ShippingOutRequest, ShippingOutRequestItem
from app.models.shop_assembly import (
    ShopAssemblyBatch,
    ShopAssemblyBatchItem,
    ShopAssemblyRequest,
    ShopAssemblyRequestItem,
    ShopAssemblyRequestOpening,
)

Product = tuple[str, str]  # (hardware_category, product_code)

# The three values an override may set. UNCLASSIFIED and MIXED only describe what is there now.
SETTABLE = frozenset(
    {
        HardwareClassificationChoice.UCH_SHOP,
        HardwareClassificationChoice.UCH_SITE,
        HardwareClassificationChoice.BY_OTHERS,
    }
)

_STORED = {
    HardwareClassificationChoice.UCH_SHOP: Classification.SHOP_HARDWARE,
    HardwareClassificationChoice.UCH_SITE: Classification.SITE_HARDWARE,
}


def _choice_of(classes: set[Classification | None], excluded: bool) -> HardwareClassificationChoice:
    if excluded:
        return HardwareClassificationChoice.BY_OTHERS
    if classes == {Classification.SHOP_HARDWARE}:
        return HardwareClassificationChoice.UCH_SHOP
    if classes == {Classification.SITE_HARDWARE}:
        return HardwareClassificationChoice.UCH_SITE
    if classes <= {None}:
        return HardwareClassificationChoice.UNCLASSIFIED
    return HardwareClassificationChoice.MIXED


def list_product_classifications(session: Session, project_id: uuid.UUID) -> list[dict]:
    """One row per product on the project's schedule: its current choice, total quantity and how many
    openings carry it. Three grouped queries for the whole schedule, never one per product."""
    totals = session.execute(
        select(
            HardwareItem.hardware_category,
            HardwareItem.product_code,
            func.sum(HardwareItem.item_quantity),
            func.count(func.distinct(HardwareItem.opening_id)),
        )
        .where(HardwareItem.project_id == project_id)
        .group_by(HardwareItem.hardware_category, HardwareItem.product_code)
    ).all()
    classes: dict[Product, set] = defaultdict(set)
    for category, code, cls in session.execute(
        select(HardwareItem.hardware_category, HardwareItem.product_code, HardwareItem.classification)
        .where(HardwareItem.project_id == project_id)
        .distinct()
    ):
        classes[(category, code)].add(cls)
    excluded = _excluded(session, project_id)

    rows = [
        {
            "hardware_category": category,
            "product_code": code,
            "quantity": int(quantity or 0),
            "opening_count": int(openings or 0),
            "choice": _choice_of(classes[(category, code)], (category, code) in excluded),
        }
        for category, code, quantity, openings in totals
    ]
    rows.sort(key=lambda r: (r["hardware_category"], r["product_code"]))
    return rows


def list_changes(session: Session, project_id: uuid.UUID, limit: int = 200) -> list[HardwareClassificationChange]:
    return list(
        session.scalars(
            select(HardwareClassificationChange)
            .where(HardwareClassificationChange.project_id == project_id)
            .order_by(HardwareClassificationChange.changed_at.desc())
            .limit(limit)
        )
    )


def _excluded(session: Session, project_id: uuid.UUID) -> set[Product]:
    return {
        (e.hardware_category, e.product_code)
        for e in session.scalars(select(ProjectExcludedItem).where(ProjectExcludedItem.project_id == project_id))
    }


def _live_shop_holds(session: Session, project_id: uuid.UUID) -> dict[Product, set[str]]:
    """Products a live shop assembly request holds, with the request or batch numbers holding them."""
    holds: dict[Product, set[str]] = defaultdict(set)
    waiting = session.execute(
        select(
            ShopAssemblyRequestItem.hardware_category,
            ShopAssemblyRequestItem.product_code,
            ShopAssemblyRequest.request_number,
        )
        .join(ShopAssemblyRequest, ShopAssemblyRequestItem.shop_assembly_request_id == ShopAssemblyRequest.id)
        .join(
            ShopAssemblyRequestOpening,
            (ShopAssemblyRequestOpening.shop_assembly_request_id == ShopAssemblyRequest.id)
            & (ShopAssemblyRequestOpening.opening_number == ShopAssemblyRequestItem.opening_number),
        )
        .where(
            ShopAssemblyRequest.project_id == project_id,
            ShopAssemblyRequest.status == ShopAssemblyRequestStatus.PENDING,
            ShopAssemblyRequestOpening.status == ShopAssemblyOpeningStatus.PENDING,
        )
    )
    for category, code, number in waiting:
        holds[(category, code)].add(number)
    batched = session.execute(
        select(
            ShopAssemblyBatchItem.hardware_category, ShopAssemblyBatchItem.product_code, ShopAssemblyBatch.batch_number
        )
        .join(ShopAssemblyBatch, ShopAssemblyBatchItem.shop_assembly_batch_id == ShopAssemblyBatch.id)
        .join(ShopAssemblyRequest, ShopAssemblyBatch.shop_assembly_request_id == ShopAssemblyRequest.id)
        .join(PullRequest, ShopAssemblyBatch.pull_request_id == PullRequest.id)
        .where(
            ShopAssemblyRequest.project_id == project_id,
            ShopAssemblyBatch.status == ShopAssemblyBatchStatus.ACTIVE,
            PullRequest.status.in_([PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS]),
        )
    )
    for category, code, number in batched:
        holds[(category, code)].add(number)
    return holds


def _on_po(session: Session, project_id: uuid.UUID) -> set[Product]:
    return {
        (category, code)
        for category, code in session.execute(
            select(HardwareItem.hardware_category, HardwareItem.product_code)
            .where(HardwareItem.project_id == project_id, HardwareItem.state == HardwareItemState.IN_PO)
            .distinct()
        )
    }


def _pending_shipping(session: Session, project_id: uuid.UUID) -> dict[Product, set[str]]:
    holds: dict[Product, set[str]] = defaultdict(set)
    for category, code, number in session.execute(
        select(
            ShippingOutRequestItem.hardware_category,
            ShippingOutRequestItem.product_code,
            ShippingOutRequest.request_number,
        )
        .join(ShippingOutRequest, ShippingOutRequestItem.shipping_out_request_id == ShippingOutRequest.id)
        .where(
            ShippingOutRequest.project_id == project_id,
            ShippingOutRequest.status == ShippingOutRequestStatus.PENDING,
        )
    ):
        holds[(category, code)].add(number)
    return holds


def set_product_classifications(
    session: Session,
    project_id: uuid.UUID,
    changes: list[tuple[str, str, HardwareClassificationChoice]],
    *,
    changed_by: str,
) -> list[HardwareClassificationChange]:
    """Apply every change or none. A refusal names each blocked product and what holds it.

    Returns the log rows written; a change to the value a product already has writes nothing."""
    if not changes:
        raise ValidationError("Pick at least one product to change.", field="changes")
    for _category, _code, to in changes:
        if to not in SETTABLE:
            raise ValidationError("A product can be set to UCH Shop, UCH Site or By Others only.", field="changes")

    current = {
        (r["hardware_category"], r["product_code"]): r["choice"]
        for r in list_product_classifications(session, project_id)
    }
    shop_rows: set[Product] = {
        (category, code)
        for category, code in session.execute(
            select(HardwareItem.hardware_category, HardwareItem.product_code)
            .where(HardwareItem.project_id == project_id, HardwareItem.classification == Classification.SHOP_HARDWARE)
            .distinct()
        )
    }
    shop_holds = _live_shop_holds(session, project_id)
    on_po = _on_po(session, project_id)
    shipping_holds = _pending_shipping(session, project_id)

    blocked: list[str] = []
    todo: list[tuple[Product, HardwareClassificationChoice, HardwareClassificationChoice]] = []
    for category, code, to in changes:
        product = (category, code)
        if product not in current:
            raise ValidationError(f"{code} ({category}) is not on this project's hardware schedule.", field="changes")
        was = current[product]
        if was == to:
            continue
        reasons: list[str] = []
        leaving_shop = (
            product in shop_rows
            and was != HardwareClassificationChoice.BY_OTHERS
            and to != HardwareClassificationChoice.UCH_SHOP
        )
        if leaving_shop and shop_holds.get(product):
            reasons.append(f"on shop assembly {', '.join(sorted(shop_holds[product]))}")
        if to == HardwareClassificationChoice.BY_OTHERS:
            if product in on_po:
                reasons.append("on a PO")
            if shipping_holds.get(product):
                reasons.append(f"on shipping request {', '.join(sorted(shipping_holds[product]))}")
        if reasons:
            blocked.append(f"{code} ({category}): {'; '.join(reasons)}")
        else:
            todo.append((product, was, to))

    if blocked:
        raise ConflictError(
            "Nothing was changed. These products cannot take that classification while something depends on it: "
            + " | ".join(blocked),
            field="changes",
        )

    now = datetime.utcnow()
    written: list[HardwareClassificationChange] = []
    for (category, code), was, to in todo:
        match = (
            (ProjectExcludedItem.project_id == project_id)
            & (ProjectExcludedItem.hardware_category == category)
            & (ProjectExcludedItem.product_code == code)
        )
        if to == HardwareClassificationChoice.BY_OTHERS:
            session.add(
                ProjectExcludedItem(
                    id=uuid.uuid4(), project_id=project_id, hardware_category=category, product_code=code
                )
            )
        else:
            session.execute(delete(ProjectExcludedItem).where(match))
            session.execute(
                update(HardwareItem)
                .where(
                    HardwareItem.project_id == project_id,
                    HardwareItem.hardware_category == category,
                    HardwareItem.product_code == code,
                )
                .values(classification=_STORED[to], updated_at=now)
            )
        change = HardwareClassificationChange(
            id=uuid.uuid4(),
            project_id=project_id,
            hardware_category=category,
            product_code=code,
            from_choice=was.value,
            to_choice=to.value,
            changed_by=changed_by,
            changed_at=now,
        )
        session.add(change)
        written.append(change)
    session.flush()
    return written
