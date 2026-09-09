"""INVENTORY VALUE: what everything in the building is worth, per GP company (#662).

Three figures - OSSA, NON-OSSA, GENERAL STOCK - each the dollar value of hardware on the shelves plus
hardware staged for shipping plus doors. Greg's formula, in the vocabulary the schema already uses:

    (project inventory qty + staged qty + stock qty + non-stock qty) x unit cost
    + every door at AVERAGE DOOR COST

Only the doors are stored (DOORS ON HAND, AVERAGE DOOR COST - see app/models/inventory_value.py).
Everything else is computed from live rows on every read, so the page can never disagree with the
warehouse screens about what is on the shelf.

Every read here is a GROUPED statement, never a walk of ORM relationships (CLAUDE.md perf rules). A
company can hold thousands of inventory rows across hundreds of projects, and the whole page is one
resolver - so the number of statements has to be a constant, not a function of how many projects the
company has.

The three buckets are a partition of the company: a project is OSSA or it is not, and the stock pool
belongs to neither because it belongs to no job. Nothing is counted twice and nothing is left out.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import PullPickLineState, PullRequestSource, PullRequestStatus
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.inventory_value import DoorsOnHand, InventoryValueSettings
from app.models.project import Project
from app.models.pull_pick_line import PullPickLine
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.warehouse import Warehouse
from app.repositories import shipping_repository

# The three figures the page shows. GENERAL_STOCK is the jobless half - the stock pool and the
# general DOORS ON HAND row - which is why it has no project side at all.
OSSA = "OSSA"
NON_OSSA = "NON_OSSA"
GENERAL_STOCK = "GENERAL_STOCK"

_CENTS = Decimal("0.01")
_ZERO = Decimal("0")


def _cents(value: Decimal | None) -> Decimal:
    return (value or _ZERO).quantize(_CENTS, rounding=ROUND_HALF_UP)


# --- the two stored rows, get-or-created so a fresh company never renders empty -------------------


def get_settings(session: Session, company: str) -> InventoryValueSettings:
    """The company's AVERAGE DOOR COST row, created at zero on first read.

    The caller commits; the create is flushed here so the resolver can serialize the row it just
    made - the same shape po_document_settings_repository.get_settings uses for its singleton.
    """
    settings = session.get(InventoryValueSettings, company)
    if settings is not None:
        return settings
    settings = InventoryValueSettings(company=company, average_door_cost=_ZERO)
    session.add(settings)
    session.flush()
    return settings


def get_general_row(session: Session, company: str) -> DoorsOnHand:
    """The company's general DOORS ON HAND row - the doors belonging to no job - created at zero.

    It exists whether or not anybody has typed a number into it, because the page shows it as a line
    of the table rather than as something you add. A company with no general row would render a table
    whose first row is missing and whose GENERAL STOCK figure silently omits doors.
    """
    row = session.scalars(
        select(DoorsOnHand).where(DoorsOnHand.company == company, DoorsOnHand.project_id.is_(None))
    ).first()
    if row is not None:
        return row
    row = DoorsOnHand(company=company, project_id=None, quantity=0)
    session.add(row)
    session.flush()
    return row


# --- the computed halves --------------------------------------------------------------------------


def _shelf_value_by_project(session: Session, company: str) -> dict[uuid.UUID, Decimal]:
    """Hardware on the shelves, per project, at the same coalesce every value view in this codebase
    applies: the PO line's cost, else the row's own off-PO cost (the SharePoint migration), else 0.

    The full `quantity` counts, deficient units included - that is what the warehouse dashboard's
    total-value tile shows, and two screens naming the same thing must not answer differently.
    Archived projects are included: archiving hides a job from the pickers, it does not empty its
    racks (#637).
    """
    rows = session.execute(
        select(
            InventoryLocationModel.project_id,
            func.coalesce(
                func.sum(
                    InventoryLocationModel.quantity
                    * func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost, 0)
                ),
                0,
            ),
        )
        .select_from(InventoryLocationModel)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .join(Project, InventoryLocationModel.project_id == Project.id)
        .where(Project.company == company)
        .group_by(InventoryLocationModel.project_id)
    ).all()
    return {row[0]: Decimal(row[1] or 0) for row in rows}


def _staged_quantities(session: Session, company: str) -> dict[tuple[uuid.UUID, str, str], int]:
    """The staging pool, per (project, category, product).

    Netted per (project, opening, category, product) first and only then summed, because that is the
    key `get_ship_ready_items` nets on: an opening that has shipped more than it staged must not lend
    its negative to a sibling opening of the same product. Both aggregates come from
    shipping_repository so this can never drift from what the shipping workspace offers to load.
    """
    fulfilled: dict[tuple, int] = {}
    for row in session.execute(shipping_repository.staged_fulfilled_stmt(company=company, by_project=True)):
        key = (row.project_id, row.opening_number, row.hardware_category, row.product_code)
        fulfilled[key] = int(row.total_requested or 0)

    shipped: dict[tuple, int] = {}
    for row in session.execute(shipping_repository.staged_shipped_stmt(company=company, by_project=True)):
        key = (row.project_id, row.opening_number, row.hardware_category, row.product_code)
        shipped[key] = int(row.total_shipped or 0)

    staged: dict[tuple[uuid.UUID, str, str], int] = defaultdict(int)
    for key, total in fulfilled.items():
        available = total - shipped.get(key, 0)
        if available > 0:
            staged[(key[0], key[2], key[3])] += available
    return dict(staged)


def _picked_unit_costs(session: Session, company: str) -> dict[tuple[uuid.UUID, str, str], Decimal]:
    """What the staged units actually cost, read off the rows they were picked from.

    Staged hardware has left the shelf, so there is no inventory row left to price it by - but there
    IS a record of exactly which rows it came off: the APPLIED pick lines (#367). Those rows are kept
    at quantity 0 and keep their cost, so walking the pick line back to its row recovers the price of
    the very units on the cart. Quantity-weighted, because one pull can take the same product off two
    rows bought at different prices.

    Lines whose row has been deleted (`inventory_location_id` is ON DELETE SET NULL) and lines whose
    row knows no cost are skipped rather than counted at zero - a missing price is not a free door
    closer, and the project-average fallback below is a better answer than 0.
    """
    effective_cost = func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost)
    rows = session.execute(
        select(
            PullRequestModel.project_id,
            PullPickLine.hardware_category,
            PullPickLine.product_code,
            func.sum(PullPickLine.quantity * effective_cost),
            func.sum(PullPickLine.quantity),
        )
        .select_from(PullPickLine)
        .join(PullRequestModel, PullPickLine.pull_request_id == PullRequestModel.id)
        .join(InventoryLocationModel, PullPickLine.inventory_location_id == InventoryLocationModel.id)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .join(Project, PullRequestModel.project_id == Project.id)
        .where(
            Project.company == company,
            PullPickLine.state == PullPickLineState.APPLIED,
            PullRequestModel.source == PullRequestSource.SHIPPING_OUT,
            PullRequestModel.status == PullRequestStatus.COMPLETED,
            effective_cost.is_not(None),
        )
        .group_by(PullRequestModel.project_id, PullPickLine.hardware_category, PullPickLine.product_code)
    ).all()

    costs: dict[tuple[uuid.UUID, str, str], Decimal] = {}
    for project_id, category, code, cost_sum, qty_sum in rows:
        if not qty_sum:
            continue
        costs[(project_id, category, code)] = Decimal(cost_sum) / Decimal(qty_sum)
    return costs


def _project_average_costs(
    session: Session, keys: list[tuple[uuid.UUID, str, str]]
) -> dict[tuple[uuid.UUID, str, str], Decimal]:
    """The fallback price for a staged product with no priced pick line behind it - hardware picked
    before #367, or picked off rows that have since been deleted.

    A plain average over the project's inventory rows for that product, zero-quantity rows included:
    a row emptied by the very pick being priced is the most relevant row there is, so weighting by
    what is left on the shelf would discard exactly the evidence wanted. Rows that know no cost are
    ignored by `avg` rather than dragging the answer toward zero.

    Narrowed to the projects and products that actually need a fallback, so the statement stays one
    grouped read of a handful of groups rather than every combo the company has ever held.
    """
    if not keys:
        return {}
    effective_cost = func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost)
    rows = session.execute(
        select(
            InventoryLocationModel.project_id,
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
            func.avg(effective_cost),
        )
        .select_from(InventoryLocationModel)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .where(
            InventoryLocationModel.project_id.in_({k[0] for k in keys}),
            InventoryLocationModel.product_code.in_({k[2] for k in keys}),
        )
        .group_by(
            InventoryLocationModel.project_id,
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
        )
    ).all()
    return {(pid, cat, code): Decimal(avg) for pid, cat, code, avg in rows if avg is not None}


def _staged_value_by_project(session: Session, company: str) -> dict[uuid.UUID, Decimal]:
    staged = _staged_quantities(session, company)
    if not staged:
        return {}
    picked = _picked_unit_costs(session, company)
    fallback = _project_average_costs(session, [key for key in staged if key not in picked])

    value: dict[uuid.UUID, Decimal] = defaultdict(Decimal)
    for key, quantity in staged.items():
        unit_cost = picked.get(key) or fallback.get(key) or _ZERO
        value[key[0]] += Decimal(quantity) * unit_cost
    return dict(value)


def _stock_pool_value(session: Session, company: str) -> Decimal:
    """The jobless pool, priced off the rows' own off-PO cost - the same expression the warehouse
    dashboard's stock tile uses. Stock scopes through its WAREHOUSE, never a project (#637)."""
    total = session.scalar(
        select(func.coalesce(func.sum(StockItemModel.quantity * func.coalesce(StockItemModel.unit_cost, 0)), 0))
        .select_from(StockItemModel)
        .join(Warehouse, StockItemModel.warehouse_id == Warehouse.id)
        .where(Warehouse.company == company)
    )
    return Decimal(total or 0)


# --- the page ------------------------------------------------------------------------------------


def _empty_bucket() -> dict:
    return {"hardware_value": _ZERO, "door_count": 0, "door_value": _ZERO, "total_value": _ZERO}


def get_inventory_value(session: Session, company: str) -> dict:
    """The whole INVENTORY VALUE page for one GP company, in six statements plus the two get-or-creates.

    The caller commits: a first read for a company creates that company's settings row and general
    DOORS ON HAND row, and those have to persist or every read would create them again.
    """
    settings = get_settings(session, company)
    get_general_row(session, company)

    shelf = _shelf_value_by_project(session, company)
    staged = _staged_value_by_project(session, company)

    door_rows = session.execute(
        select(
            DoorsOnHand.id,
            DoorsOnHand.project_id,
            DoorsOnHand.quantity,
            Project.project_id,
            Project.description,
            Project.off_site_storage_agreement,
        )
        .select_from(DoorsOnHand)
        .outerjoin(Project, DoorsOnHand.project_id == Project.id)
        .where(DoorsOnHand.company == company)
    ).all()

    ossa_flags = dict(
        session.execute(select(Project.id, Project.off_site_storage_agreement).where(Project.company == company)).all()
    )

    average_door_cost = Decimal(settings.average_door_cost or 0)
    buckets = {OSSA: _empty_bucket(), NON_OSSA: _empty_bucket(), GENERAL_STOCK: _empty_bucket()}

    # Hardware. Every project of the company falls in exactly one of the two project buckets, and a
    # project with no rows at all contributes nothing rather than being skipped as unknown.
    for project_id, value in list(shelf.items()) + list(staged.items()):
        bucket = OSSA if ossa_flags.get(project_id) else NON_OSSA
        buckets[bucket]["hardware_value"] += value
    buckets[GENERAL_STOCK]["hardware_value"] = _stock_pool_value(session, company)

    # Doors.
    rows = []
    for row_id, project_id, quantity, project_number, project_name, is_ossa in door_rows:
        is_general = project_id is None
        rows.append(
            {
                "id": row_id,
                "project_id": project_id,
                "project_number": project_number,
                "project_name": project_name,
                "is_ossa": bool(is_ossa),
                "quantity": int(quantity),
            }
        )
        bucket = GENERAL_STOCK if is_general else (OSSA if is_ossa else NON_OSSA)
        buckets[bucket]["door_count"] += int(quantity)

    # The general row first, then OSSA projects, then the rest - the order Greg's table reads in.
    rows.sort(key=lambda r: (r["project_id"] is not None, not r["is_ossa"], r["project_number"] or ""))

    for bucket in buckets.values():
        bucket["hardware_value"] = _cents(bucket["hardware_value"])
        bucket["door_value"] = _cents(Decimal(bucket["door_count"]) * average_door_cost)
        # Summed from the rounded halves so the caption ("hardware $X + doors $Y") always adds up to
        # the figure printed above it.
        bucket["total_value"] = bucket["hardware_value"] + bucket["door_value"]

    return {
        "company": company,
        "ossa": buckets[OSSA],
        "non_ossa": buckets[NON_OSSA],
        "general_stock": buckets[GENERAL_STOCK],
        "average_door_cost": _cents(average_door_cost),
        "average_door_cost_updated_at": settings.updated_at,
        "average_door_cost_updated_by": settings.updated_by,
        "doors_on_hand": rows,
        "general_door_count": buckets[GENERAL_STOCK]["door_count"],
        "ossa_door_count": buckets[OSSA]["door_count"],
        "non_ossa_door_count": buckets[NON_OSSA]["door_count"],
        "total_door_count": sum(b["door_count"] for b in buckets.values()),
    }


# --- writes ----------------------------------------------------------------------------------------


def save_doors_on_hand(
    session: Session,
    company: str,
    project_id: uuid.UUID | None,
    quantity: int,
) -> DoorsOnHand:
    """Set a DOORS ON HAND row's count, creating the row if this is the first time it is named.

    An upsert rather than a create/update pair because the page has no create step: picking a project
    off the "Add project" control saves it at zero, and typing into the cell saves it again.

    A project of another company is refused as NOT FOUND, the way tenancy.py refuses everything else -
    a "forbidden" answer would confirm the row exists and turn this into an id oracle.
    """
    if quantity < 0:
        raise ValidationError("Doors on hand cannot be negative.", field="quantity")

    if project_id is None:
        row = get_general_row(session, company)
        row.quantity = quantity
        session.flush()
        return row

    owner = session.scalar(select(Project.company).where(Project.id == project_id))
    if owner != company:
        raise NotFoundError(f"Project {project_id} not found")

    row = session.scalars(
        select(DoorsOnHand).where(DoorsOnHand.company == company, DoorsOnHand.project_id == project_id)
    ).first()
    if row is None:
        row = DoorsOnHand(company=company, project_id=project_id, quantity=quantity)
        session.add(row)
    else:
        row.quantity = quantity
    session.flush()
    return row


def company_of_doors_on_hand(session: Session, row_id: uuid.UUID) -> str:
    """Whose row this is, for the scope check a delete has to make BEFORE it deletes anything."""
    company = session.scalar(select(DoorsOnHand.company).where(DoorsOnHand.id == row_id))
    if company is None:
        raise NotFoundError(f"Doors on hand row {row_id} not found")
    return company


def remove_doors_on_hand(session: Session, row_id: uuid.UUID) -> DoorsOnHand:
    """Drop a project's DOORS ON HAND row. Returns the row so the caller can read its company back.

    The general row is not removable: it is a line of the table rather than something somebody added,
    and a company without one has a GENERAL STOCK figure that silently omits doors.
    """
    row = session.get(DoorsOnHand, row_id)
    if row is None:
        raise NotFoundError(f"Doors on hand row {row_id} not found")
    if row.project_id is None:
        raise ValidationError("The general doors on hand row cannot be removed; set it to 0 instead.")
    session.delete(row)
    session.flush()
    return row


def set_average_door_cost(session: Session, company: str, amount: Decimal, actor: str | None) -> InventoryValueSettings:
    if amount < 0:
        raise ValidationError("Average door cost cannot be negative.", field="amount")
    settings = get_settings(session, company)
    settings.average_door_cost = _cents(Decimal(amount))
    settings.updated_by = actor
    # `onupdate` only fires when some other column changed; re-saving the same figure is still a
    # deliberate act by a named person, and the caption on the page says when it last happened.
    settings.updated_at = datetime.utcnow()
    session.flush()
    return settings


def list_companies_with_projects(session: Session, scope: str | None) -> list[str]:
    """The GP companies the page can be shown for: every company that owns a project.

    Deliberately read off projects rather than off the relay's company list - INVENTORY VALUE is a
    read of rows Nexus already holds, and it must still answer when the relay is down. A scoped
    caller sees only their own company (#637).
    """
    stmt = select(Project.company).distinct()
    if scope is not None:
        stmt = stmt.where(Project.company == scope)
    return sorted(c for c in session.scalars(stmt).all() if c)
