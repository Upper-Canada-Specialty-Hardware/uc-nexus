"""Manual override of a project's hardware classifications after import (#735).

A product's classification is the import's three-way choice - UCH Shop, UCH Site, By Others - stored
on two axes: hardware_items.classification (SHOP_HARDWARE / SITE_HARDWARE) for every schedule row of
the product, and a project_excluded_items row for By Others. The override writes both the same way
the import's finalize does, so nothing downstream can tell an overridden product from an imported one.

Since #1443 a product's UCH Shop / UCH Site also has its own per-project list,
project_product_classifications, which no schedule is tied to. The product owner ruled that a newer
schedule appends to it and never changes what is on it, and that a product a newer schedule dropped is
remembered. So this page is where a listed product's classification is changed: every Shop / Site it
sets is written to the list as well as the rows, and it shows the list's products a schedule no longer
has. By Others stays a project_excluded_items row and is never listed.

What a change does is planned before it is written (#1050), and the page shows that plan first:

- Hardware that already went somewhere - to the shop on a completed shop assembly pull, or out on a
  shipment that was not cancelled - stays as it went. A change applies to what is still owed, and its
  log row records what had already gone out. (#977 used to lock the product instead.)
- Site hardware cannot be pulled into the shop. A product leaving shop comes off every opening still
  waiting on a pending shop assembly request (the manager is told); an active batch whose pull has not
  finished still refuses it, because that hardware is reserved and on the floor for the shop.
- By Others is not UCH's to order or ship. The product's schedule rows stop counting as ordered; a PO
  for it, or a pending shipping request asking for it, is left alone and said so, because neither
  depends on the classification - what arrives lands in the job's inventory like any extra.

Every change is logged in hardware_classification_changes.
"""

import uuid
from collections import defaultdict
from datetime import datetime

from sqlalchemy import delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, ValidationError
from app.models.enums import (
    Classification,
    HardwareClassificationChoice,
    HardwareItemState,
    NotificationType,
    PullRequestStatus,
    ShipmentStatus,
    ShippingOutRequestStatus,
    ShopAssemblyBatchStatus,
    ShopAssemblyOpeningStatus,
    ShopAssemblyRequestStatus,
)
from app.models.hardware import HardwareItem
from app.models.hardware_classification_change import HardwareClassificationChange
from app.models.project_excluded_item import ProjectExcludedItem
from app.models.project_product_classification import ProjectProductClassification
from app.models.pull_request import PullRequest
from app.models.shipping import PackingSlip, PackingSlipItem
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

# The choices that mean a product has been classified (#1392). The product owner ruled that such a
# product can't be changed to By Others, on this page or through a schedule replace: By Others treats
# the item as if it doesn't exist, which the work already planned around a classified product - POs,
# shop requests, shipping - does not survive. Its first classification at import may still be By Others,
# and By Others -> Shop / Site stays allowed.
_CLASSIFIED = frozenset(
    {
        HardwareClassificationChoice.UCH_SHOP,
        HardwareClassificationChoice.UCH_SITE,
        HardwareClassificationChoice.MIXED,
    }
)
_LABEL = {
    HardwareClassificationChoice.UCH_SHOP: "UCH Shop",
    HardwareClassificationChoice.UCH_SITE: "UCH Site",
    HardwareClassificationChoice.MIXED: "a mix of UCH Shop and UCH Site",
}


def _by_others_refusal(was: HardwareClassificationChoice) -> str:
    return f"it is already classified {_LABEL[was]}, and a classified product can't be changed to By Others"


def refuse_classified_into_by_others(session: Session, project_id: uuid.UUID, excluded: set[Product]) -> None:
    """Refuse a finalize whose By Others list takes in a product the project already has classified (#1392).

    Called before the finalize rewrites the schedule rows, so the choice read is what the project held, a
    product only on the classification list (#1443) included. A product new to the project, never
    classified, or already By Others passes."""
    if not excluded:
        return
    current = {
        (r["hardware_category"], r["product_code"]): r["choice"]
        for r in list_product_classifications(session, project_id)
    }
    refused = [
        f"{code} ({category}): {_by_others_refusal(current[(category, code)])}"
        for category, code in sorted(excluded)
        if current.get((category, code)) in _CLASSIFIED
    ]
    if refused:
        raise ValidationError("Nothing was saved. " + " | ".join(refused), field="excludedItems")


_STORED = {
    HardwareClassificationChoice.UCH_SHOP: Classification.SHOP_HARDWARE,
    HardwareClassificationChoice.UCH_SITE: Classification.SITE_HARDWARE,
}
_CHOICE_OF_STORED = {stored: choice for choice, stored in _STORED.items()}


def listed_classifications(session: Session, project_id: uuid.UUID) -> dict[Product, Classification]:
    """The project's classification list (#1443): {product: Shop / Site}, in one query."""
    return {
        (category, code): classification
        for category, code, classification in session.execute(
            select(
                ProjectProductClassification.hardware_category,
                ProjectProductClassification.product_code,
                ProjectProductClassification.classification,
            ).where(ProjectProductClassification.project_id == project_id)
        )
    }


def write_list(
    session: Session,
    project_id: uuid.UUID,
    products: dict[Product, Classification],
    *,
    updated_by: str | None,
) -> None:
    """Put each product on the project's classification list with this value, adding its row or replacing
    the value it had (#1443). Callers hold the project row lock, so nothing else writes the list meanwhile."""
    if not products:
        return
    now = datetime.utcnow()
    stmt = pg_insert(ProjectProductClassification).values(
        [
            {
                "id": uuid.uuid4(),
                "project_id": project_id,
                "hardware_category": category,
                "product_code": code,
                "classification": classification,
                "created_at": now,
                "updated_at": now,
                "updated_by": updated_by,
            }
            for (category, code), classification in sorted(products.items())
        ]
    )
    session.execute(
        stmt.on_conflict_do_update(
            constraint="uq_project_product_classifications",
            set_={
                "classification": stmt.excluded.classification,
                "updated_at": stmt.excluded.updated_at,
                "updated_by": stmt.excluded.updated_by,
            },
        )
    )


def refuse_import_reclassifying_listed(
    listed: dict[Product, Classification], given: dict[Product, set[Classification]]
) -> None:
    """Refuse a finalize that gives a listed product a classification other than the list's (#1443).

    The product owner ruled that a schedule import doesn't change an existing product's Site / Shop: that is
    done on the project's Hardware Classifications page, which shows what the change does first. Called
    before the finalize writes anything, so a refusal leaves the project as it was."""
    refused = [
        f"{code} ({category}) is {_LABEL[_CHOICE_OF_STORED[listed[(category, code)]]]}"
        for category, code in sorted(given)
        if (category, code) in listed and given[(category, code)] != {listed[(category, code)]}
    ]
    if refused:
        raise ValidationError(
            "Nothing was saved. A schedule import can't change the classification of a product this project "
            "already has; change it on the project's Hardware Classifications page. " + " | ".join(refused),
            field="classifications",
        )


def _choice_of(
    classes: set[Classification | None], excluded: bool, listed: Classification | None = None
) -> HardwareClassificationChoice:
    if excluded:
        return HardwareClassificationChoice.BY_OTHERS
    # A listed product's classification is the list's, whatever its schedule rows say (#1443).
    if listed is not None:
        return _CHOICE_OF_STORED[listed]
    if classes == {Classification.SHOP_HARDWARE}:
        return HardwareClassificationChoice.UCH_SHOP
    if classes == {Classification.SITE_HARDWARE}:
        return HardwareClassificationChoice.UCH_SITE
    if classes <= {None}:
        return HardwareClassificationChoice.UNCLASSIFIED
    return HardwareClassificationChoice.MIXED


def list_product_classifications(session: Session, project_id: uuid.UUID) -> list[dict]:
    """One row per product on the project's schedule or its classification list (#1443): its current
    choice, total quantity, how many openings carry it, and whether the schedule has it at all. A product
    only on the list - one a newer schedule dropped before anybody ordered it - reads 0 and 0. Four
    queries for the whole project, never one per product."""
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
    listed = listed_classifications(session, project_id)

    rows = [
        {
            "hardware_category": category,
            "product_code": code,
            "quantity": int(quantity or 0),
            "opening_count": int(openings or 0),
            "choice": _choice_of(classes[(category, code)], (category, code) in excluded, listed.get((category, code))),
            "on_schedule": True,
        }
        for category, code, quantity, openings in totals
    ]
    on_schedule = {(r["hardware_category"], r["product_code"]) for r in rows}
    rows.extend(
        {
            "hardware_category": category,
            "product_code": code,
            "quantity": 0,
            "opening_count": 0,
            "choice": _choice_of(set(), (category, code) in excluded, classification),
            "on_schedule": False,
        }
        for (category, code), classification in listed.items()
        if (category, code) not in on_schedule
    )
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


LABEL = {
    HardwareClassificationChoice.UCH_SHOP: "UCH Shop",
    HardwareClassificationChoice.UCH_SITE: "UCH Site",
    HardwareClassificationChoice.BY_OTHERS: "By Others",
    HardwareClassificationChoice.UNCLASSIFIED: "Unclassified",
    HardwareClassificationChoice.MIXED: "Mixed",
}


def _waiting_shop_lines(session: Session, project_id: uuid.UUID) -> dict[Product, dict[str, set[str]]]:
    """Products on openings still waiting on a pending shop assembly request: {product: {request: openings}}.

    Nothing is held for these yet - a waiting opening has never been batched - so a change that takes
    the product out of the shop takes it off these openings (#1050)."""
    waiting: dict[Product, dict[str, set[str]]] = defaultdict(lambda: defaultdict(set))
    for category, code, number, opening in session.execute(
        select(
            ShopAssemblyRequestItem.hardware_category,
            ShopAssemblyRequestItem.product_code,
            ShopAssemblyRequest.request_number,
            ShopAssemblyRequestItem.opening_number,
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
    ):
        waiting[(category, code)][number].add(opening)
    return waiting


def _batches_being_pulled(session: Session, project_id: uuid.UUID) -> dict[Product, dict[str, PullRequestStatus]]:
    """Products on an active shop assembly batch whose pull has not finished: hardware is reserved and
    on the floor for the shop, so a change that takes the product out of the shop waits for it. Each
    batch number with its pull's status: one not started yet is undone by a discard, not a cancel (#1956)."""
    holds: dict[Product, dict[str, PullRequestStatus]] = defaultdict(dict)
    for category, code, number, status in session.execute(
        select(
            ShopAssemblyBatchItem.hardware_category,
            ShopAssemblyBatchItem.product_code,
            ShopAssemblyBatch.batch_number,
            PullRequest.status,
        )
        .join(ShopAssemblyBatch, ShopAssemblyBatchItem.shop_assembly_batch_id == ShopAssemblyBatch.id)
        .join(ShopAssemblyRequest, ShopAssemblyBatch.shop_assembly_request_id == ShopAssemblyRequest.id)
        .join(PullRequest, ShopAssemblyBatch.pull_request_id == PullRequest.id)
        .where(
            ShopAssemblyRequest.project_id == project_id,
            ShopAssemblyBatch.status == ShopAssemblyBatchStatus.ACTIVE,
            PullRequest.status.in_([PullRequestStatus.PENDING, PullRequestStatus.IN_PROGRESS]),
        )
    ):
        holds[(category, code)][number] = status
    return holds


def _went_out(session: Session, project_id: uuid.UUID) -> dict[Product, set[str]]:
    """Where a product's hardware already went: "went to the shop on <batch>" for a completed shop
    assembly pull, "shipped on <slip>" for a line on a shipment that was not cancelled.

    #1050 lifted the #977 lock: this is history, shown before a change and written into its log row,
    and a change applies to what is still owed. The batch and the shipment stay what they were."""
    gone: dict[Product, set[str]] = defaultdict(set)
    to_shop = session.execute(
        select(
            ShopAssemblyBatchItem.hardware_category, ShopAssemblyBatchItem.product_code, ShopAssemblyBatch.batch_number
        )
        .join(ShopAssemblyBatch, ShopAssemblyBatchItem.shop_assembly_batch_id == ShopAssemblyBatch.id)
        .join(ShopAssemblyRequest, ShopAssemblyBatch.shop_assembly_request_id == ShopAssemblyRequest.id)
        .join(PullRequest, ShopAssemblyBatch.pull_request_id == PullRequest.id)
        .where(
            ShopAssemblyRequest.project_id == project_id,
            PullRequest.status == PullRequestStatus.COMPLETED,
        )
    )
    for category, code, number in to_shop:
        gone[(category, code)].add(f"went to the shop on {number}")
    shipped = session.execute(
        select(PackingSlipItem.hardware_category, PackingSlipItem.product_code, PackingSlip.packing_slip_number)
        .join(PackingSlip, PackingSlipItem.packing_slip_id == PackingSlip.id)
        .where(
            PackingSlip.project_id == project_id,
            PackingSlip.status != ShipmentStatus.CANCELLED,
            PackingSlipItem.is_manual.is_(False),
        )
    )
    for category, code, number in shipped:
        gone[(category, code)].add(f"shipped on {number}")
    return gone


def _on_po(session: Session, project_id: uuid.UUID) -> dict[Product, dict[str, int]]:
    """Schedule rows ordered on a PO: {product: {po number: rows}}. The link is bookkeeping for the
    import screen's Ordered / On Order figures; the PO itself does not depend on the classification."""
    from app.models.purchase_order import POLineItem, PurchaseOrder

    linked: dict[Product, dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for category, code, po_number, rows in session.execute(
        select(
            HardwareItem.hardware_category,
            HardwareItem.product_code,
            PurchaseOrder.po_number,
            func.count(HardwareItem.id),
        )
        .outerjoin(POLineItem, HardwareItem.po_line_item_id == POLineItem.id)
        .outerjoin(PurchaseOrder, POLineItem.po_id == PurchaseOrder.id)
        .where(HardwareItem.project_id == project_id, HardwareItem.state == HardwareItemState.IN_PO)
        .group_by(HardwareItem.hardware_category, HardwareItem.product_code, PurchaseOrder.po_number)
    ):
        linked[(category, code)][po_number or "a PO"] += int(rows)
    return linked


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


def plan_product_classifications(
    session: Session,
    project_id: uuid.UUID,
    changes: list[tuple[str, str, HardwareClassificationChoice]],
) -> list[dict]:
    """What each change would do, before anything is written (#1050). One entry per product that would
    actually change, each with four lists of plain sentences:

    - went_out: hardware already sent under the current classification. History - it stays as it went.
    - adjusts: in-flight work that saving changes (a shop request losing the product, PO links cleared).
    - unaffected: work that touches the product but that the change leaves alone, said so on purpose.
    - blocks: what refuses the change. Only a shop batch still being pulled does.
    """
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
    waiting = _waiting_shop_lines(session, project_id)
    being_pulled = _batches_being_pulled(session, project_id)
    on_po = _on_po(session, project_id)
    shipping = _pending_shipping(session, project_id)
    went_out = _went_out(session, project_id)

    plans: list[dict] = []
    for category, code, to in changes:
        product = (category, code)
        # A product a newer schedule dropped is still the project's while it is on the list (#1443).
        if product not in current:
            raise ValidationError(
                f"{code} ({category}) is not on this project's hardware schedule or classification list.",
                field="changes",
            )
        was = current[product]
        if was == to:
            continue
        if to == HardwareClassificationChoice.BY_OTHERS and was in _CLASSIFIED:
            plans.append(
                {
                    "hardware_category": category,
                    "product_code": code,
                    "from_choice": was,
                    "to_choice": to,
                    "went_out": [],
                    "adjusts": [],
                    "unaffected": [],
                    "blocks": [_by_others_refusal(was)],
                    "leaves_shop_requests": False,
                }
            )
            continue
        adjusts: list[str] = []
        unaffected: list[str] = []
        blocks: list[str] = []
        leaving_shop = (
            product in shop_rows
            and was != HardwareClassificationChoice.BY_OTHERS
            and to != HardwareClassificationChoice.UCH_SHOP
        )
        if leaving_shop:
            for number, status in sorted(being_pulled.get(product, {}).items()):
                if status == PullRequestStatus.PENDING:
                    # #1956: an unstarted pull can't be cancelled; the batch is discarded instead.
                    blocks.append(
                        f"on shop assembly batch {number}, whose pull hasn't started - discard batch {number} "
                        "on the Shop Assembly page first"
                    )
                else:
                    blocks.append(
                        f"on shop assembly batch {number}, still being pulled - finish or cancel the pull first"
                    )
            for number, openings in sorted(waiting.get(product, {}).items()):
                adjusts.append(
                    f"comes off shop assembly request {number} (opening {', '.join(sorted(openings))}); "
                    "the Shop Assembly Manager is told"
                )
        if to == HardwareClassificationChoice.BY_OTHERS:
            for po_number, rows in sorted(on_po.get(product, {}).items()):
                plural = "s" if rows != 1 else ""
                adjusts.append(f"{rows} schedule row{plural} no longer count as ordered on {po_number}")
                unaffected.append(
                    f"{po_number} itself is unaffected - what arrives lands in the job's inventory like any extra"
                )
            for number in sorted(shipping.get(product, ())):
                unaffected.append(f"shipping request {number} asks for it and is left as it is")
        plans.append(
            {
                "hardware_category": category,
                "product_code": code,
                "from_choice": was,
                "to_choice": to,
                "went_out": sorted(went_out.get(product, ())),
                "adjusts": adjusts,
                "unaffected": unaffected,
                "blocks": blocks,
                "leaves_shop_requests": leaving_shop and bool(waiting.get(product)),
            }
        )
    return plans


def _pending_shop_requests(session: Session, project_id: uuid.UUID) -> list[ShopAssemblyRequest]:
    """The project's pending shop requests with their lines and openings, for the products a save takes
    off them. Read once per save (#1892), not once per product leaving the shop: each product's pass
    re-read every request and then walked its lines and openings one lazy load at a time."""
    return list(
        session.scalars(
            select(ShopAssemblyRequest)
            .options(selectinload(ShopAssemblyRequest.items), selectinload(ShopAssemblyRequest.openings))
            .where(
                ShopAssemblyRequest.project_id == project_id,
                ShopAssemblyRequest.status == ShopAssemblyRequestStatus.PENDING,
            )
            # Read after the caller locked these requests: fresh, not what the session saw.
            .execution_options(populate_existing=True)
        )
        .unique()
        .all()
    )


def _take_off_waiting_shop_openings(
    session: Session,
    project_id: uuid.UUID,
    product: Product,
    to: HardwareClassificationChoice,
    *,
    changed_by: str,
    requests: list[ShopAssemblyRequest],
) -> None:
    """Remove a product leaving the shop from every opening still waiting on a pending shop request.

    An opening left with nothing on it is dismissed - the same write-off the manager makes by hand -
    and a request left with nothing waiting closes out. One notice per request tells the manager.

    `requests` is `_pending_shop_requests`, read once for the whole save. An earlier product's pass may
    have closed one out, which is then no longer pending and is passed over, as a fresh read would."""
    from app.repositories.shop_assembly_repository import _close_if_nothing_pending
    from app.services.notification_service import SHOP_ASSEMBLY_MANAGER_RECIPIENT_ROLE, create_notification

    category, code = product
    now = datetime.utcnow()
    for request in requests:
        if request.status != ShopAssemblyRequestStatus.PENDING:
            continue
        waiting = {o.opening_number: o for o in request.openings if o.status == ShopAssemblyOpeningStatus.PENDING}
        lines = [
            i
            for i in request.items
            if i.hardware_category == category and i.product_code == code and i.opening_number in waiting
        ]
        if not lines:
            continue
        touched = sorted({i.opening_number for i in lines})
        for line in lines:
            session.delete(line)
        session.flush()
        session.refresh(request)
        left = {i.opening_number for i in request.items}
        for number in touched:
            if number not in left:
                opening = waiting[number]
                opening.status = ShopAssemblyOpeningStatus.DISMISSED
                opening.dismissed_by = changed_by
                opening.dismissed_at = now
                opening.dismissal_reason = f"Nothing left for the shop: {code} changed to {LABEL[to]}"
        _close_if_nothing_pending(session, request, closed_by=changed_by)
        create_notification(
            session,
            project_id,
            SHOP_ASSEMBLY_MANAGER_RECIPIENT_ROLE,
            NotificationType.CLASSIFICATION_CHANGED,
            f"{code} ({category}) changed to {LABEL[to]} by {changed_by}, so it came off shop assembly request "
            f"{request.request_number} (opening {', '.join(touched)}).",
        )


def _lock_pending_shop_requests(session: Session, project_id: uuid.UUID) -> None:
    """Row-lock every pending shop request on the project, in id order (the order lock_rows takes)."""
    from app.services.locking import lock_rows

    ids = session.scalars(
        select(ShopAssemblyRequest.id).where(
            ShopAssemblyRequest.project_id == project_id,
            ShopAssemblyRequest.status == ShopAssemblyRequestStatus.PENDING,
        )
    ).all()
    lock_rows(session, ShopAssemblyRequest, list(ids))


def _refuse_blocked(plans: list[dict]) -> None:
    """Refuse the whole change when any product is blocked, naming each one and what holds it."""
    blocked = [
        f"{p['product_code']} ({p['hardware_category']}): {'; '.join(p['blocks'])}" for p in plans if p["blocks"]
    ]
    if blocked:
        raise ConflictError(
            "Nothing was changed. These products cannot take that classification while something depends on it: "
            + " | ".join(blocked),
            field="changes",
        )


def _record_change(
    session: Session, project_id: uuid.UUID, plan: dict, *, changed_by: str, now: datetime
) -> HardwareClassificationChange:
    change = HardwareClassificationChange(
        id=uuid.uuid4(),
        project_id=project_id,
        hardware_category=plan["hardware_category"],
        product_code=plan["product_code"],
        from_choice=plan["from_choice"].value,
        to_choice=plan["to_choice"].value,
        changed_by=changed_by,
        changed_at=now,
        # What had already gone out, and what saving changed - so the log reads the change in full.
        note="; ".join(plan["went_out"] + plan["adjusts"]) or None,
    )
    session.add(change)
    return change


def plan_import_reclassification(
    session: Session,
    project_id: uuid.UUID,
    stored: dict[Product, Classification],
    listed: dict[Product, Classification],
) -> list[dict]:
    """The override's plan for an import finalize that settles a Mixed product on one Site/Shop (#1442).

    A finalize writes the classification it was given onto every row of the product (#1264), which for a
    product that already holds Site/Shop is the same change the override page makes, so it is held to the
    same plan: refused while a shop batch for the product is still being pulled, and a product leaving the
    shop comes off the openings still waiting on a pending shop request. Called by the finalize under its
    project lock and BEFORE it rewrites the schedule rows, so `current` is what the project held.

    Since #1443 this is the unlisted products that already hold a classification. A listed product's
    classification is the project's list, which a finalize is refused for changing
    (refuse_import_reclassifying_listed). A product new to the project, or whose rows were never classified,
    is taking its first value; a By Others product stays By Others. What is left is a Mixed product (not
    listed because its rows disagree) and, rarely, one whose rows agree but which the list does not hold -
    both already hold Shop or Site, so a different answer is a change to work already planned around it.
    Pending shop requests are locked first, in the order set_product_classifications takes them.
    """
    unlisted = {product: value for product, value in stored.items() if product not in listed}
    if not unlisted:
        return []
    _lock_pending_shop_requests(session, project_id)
    current = {
        (r["hardware_category"], r["product_code"]): r["choice"]
        for r in list_product_classifications(session, project_id)
    }
    changes = [
        (category, code, _CHOICE_OF_STORED[classification])
        for (category, code), classification in sorted(unlisted.items())
        if current.get((category, code)) in _CLASSIFIED
        and current[(category, code)] != _CHOICE_OF_STORED[classification]
    ]
    if not changes:
        return []
    plans = plan_product_classifications(session, project_id, changes)
    _refuse_blocked(plans)
    return plans


def apply_import_reclassification(
    session: Session, project_id: uuid.UUID, plans: list[dict], *, changed_by: str
) -> list[HardwareClassificationChange]:
    """What an import's reclassification of a Mixed product does beyond the rows the finalize itself
    rewrites (#1442): a product leaving the shop comes off waiting shop openings (the manager is told), and
    every change is logged where the override page's history reads it."""
    now = datetime.utcnow()
    written: list[HardwareClassificationChange] = []
    pending: list[ShopAssemblyRequest] | None = None
    for plan in plans:
        if plan["leaves_shop_requests"]:
            if pending is None:
                pending = _pending_shop_requests(session, project_id)
            _take_off_waiting_shop_openings(
                session,
                project_id,
                (plan["hardware_category"], plan["product_code"]),
                plan["to_choice"],
                changed_by=changed_by,
                requests=pending,
            )
        written.append(_record_change(session, project_id, plan, changed_by=changed_by, now=now))
    session.flush()
    return written


def set_product_classifications(
    session: Session,
    project_id: uuid.UUID,
    changes: list[tuple[str, str, HardwareClassificationChoice]],
    *,
    changed_by: str,
) -> list[HardwareClassificationChange]:
    """Apply every change or none - exactly what plan_product_classifications showed. A refusal names
    each blocked product and what holds it.

    Returns the log rows written; a change to the value a product already has writes nothing.

    The project's pending shop requests are locked first, in id order, and the plan is built under that
    lock (#1156). Batch, dismiss, reject and discard each lock the request they decide (#1121); planned
    from unlocked reads, a batch committed at the same moment could leave a site product on a live shop
    pull, or a batch whose request lines this change then deleted.

    The project row is locked before them (#1425): a shop request raised at the same moment is checked
    against the classification after this commits, not before, and a finalize, which takes the same lock,
    reads the classification list (#1443) only after this has written it.

    Every UCH Shop / UCH Site set is written to the project's classification list as well as the rows
    (#1443). A product only on the list has no rows, so the list is all its change writes."""
    from app.models.project import Project

    session.execute(select(Project.id).where(Project.id == project_id).with_for_update(key_share=True))
    _lock_pending_shop_requests(session, project_id)
    plans = plan_product_classifications(session, project_id, changes)
    _refuse_blocked(plans)

    now = datetime.utcnow()
    written: list[HardwareClassificationChange] = []
    # Read under the lock above, once for every product the save takes off them (#1892).
    pending: list[ShopAssemblyRequest] | None = None
    for plan in plans:
        category, code = plan["hardware_category"], plan["product_code"]
        to = plan["to_choice"]
        product_rows = (
            (HardwareItem.project_id == project_id)
            & (HardwareItem.hardware_category == category)
            & (HardwareItem.product_code == code)
        )
        match = (
            (ProjectExcludedItem.project_id == project_id)
            & (ProjectExcludedItem.hardware_category == category)
            & (ProjectExcludedItem.product_code == code)
        )
        if plan["leaves_shop_requests"]:
            if pending is None:
                pending = _pending_shop_requests(session, project_id)
            _take_off_waiting_shop_openings(
                session, project_id, (category, code), to, changed_by=changed_by, requests=pending
            )
        if to == HardwareClassificationChoice.BY_OTHERS:
            # Only an unclassified product gets here (#1392), and an unclassified product is never listed.
            session.add(
                ProjectExcludedItem(
                    id=uuid.uuid4(), project_id=project_id, hardware_category=category, product_code=code
                )
            )
            # The ordered link is the import screen's bookkeeping; By Others is not UCH's to order.
            session.execute(
                update(HardwareItem)
                .where(product_rows, HardwareItem.state == HardwareItemState.IN_PO)
                .values(state=HardwareItemState.AVAILABLE, po_line_item_id=None, updated_at=now)
            )
        else:
            session.execute(delete(ProjectExcludedItem).where(match))
            session.execute(update(HardwareItem).where(product_rows).values(classification=_STORED[to], updated_at=now))
            write_list(session, project_id, {(category, code): _STORED[to]}, updated_by=changed_by)
        written.append(_record_change(session, project_id, plan, changed_by=changed_by, now=now))
    session.flush()
    return written
