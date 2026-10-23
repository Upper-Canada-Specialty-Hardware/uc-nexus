"""INVENTORY VALUE: what everything in the building is worth, per GP company (#662).

Three figures - OSSA, NON-OSSA, GENERAL STOCK - each the dollar value of hardware on the shelves plus
hardware staged for shipping (or picked for a pull still in progress, #1939) plus doors. Greg's formula,
in the vocabulary the schema already uses:

    (project inventory qty + staged qty + stock qty + non-stock qty) x unit cost
    + every door at AVERAGE DOOR COST

Only the doors are stored (DOORS ON HAND, AVERAGE DOOR COST - see app/models/inventory_value.py).
Everything else is computed from live rows on every read, so the page can never disagree with the
warehouse screens about what is on the shelf.

Every read here is a GROUPED statement, never a walk of ORM relationships (CLAUDE.md perf rules). A
company can hold thousands of inventory rows across hundreds of projects, and the whole page is one
resolver - so the number of statements has to be a constant, not a function of how many projects the
company has.

The four buckets are a partition of the company: a project is OSSA or it is not, and the pool belongs
to neither because it belongs to no job - it splits Stock / Overhead by each row's own kind (#832).
Nothing is counted twice and nothing is left out.

Each bucket's hardware is also split by currency (#1557). A unit bought on a USD purchase order costs US
dollars, and adding US$100 to the Canadian figure as C$100 misstated it. So hardware priced in US
dollars is summed apart, as `usd_hardware_value`, and is in neither `hardware_value` nor `total_value`.
There is no conversion and no exchange rate - the product owner ruled the two figures are shown side by
side, each in its own currency. A row's currency is its PO's when it is priced off a PO line, else its
own `cost_currency`; null, blank and CAD are all Canadian dollars.
"""

import uuid
from collections import defaultdict
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import and_, case, func, or_, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.currency import USD
from app.demo import DEMO_COMPANY
from app.errors import NotFoundError, ValidationError
from app.models.enums import PoolKind, PullPickLineState, PullRequestSource, PullRequestStatus
from app.models.inventory import InventoryLocation as InventoryLocationModel
from app.models.inventory_value import DoorsOnHand, InventoryValueSettings
from app.models.project import Project
from app.models.pull_pick_line import PullPickLine
from app.models.pull_request import PullRequest as PullRequestModel
from app.models.purchase_order import POLineItem as POLineItemModel
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.stock_item import StockItem as StockItemModel
from app.models.warehouse import Warehouse
from app.repositories import shipping_repository, warehouse

# The three figures the page shows. GENERAL_STOCK is the jobless half - the stock pool and the
# general DOORS ON HAND row - which is why it has no project side at all.
OSSA = "OSSA"
NON_OSSA = "NON_OSSA"
GENERAL_STOCK = "GENERAL_STOCK"
# The Overhead half of the pool (#832). Hardware only: the general DOORS ON HAND row stays with
# GENERAL_STOCK, so doors are never split between the two.
OVERHEAD = "OVERHEAD"

_CENTS = Decimal("0.01")
_ZERO = Decimal("0")


# inventory_value_settings.average_door_cost is Numeric(12, 2) (#1211).
_MAX_DOOR_COST = Decimal(10) ** 10


def _cents(value: Decimal | None) -> Decimal:
    return (value or _ZERO).quantize(_CENTS, rounding=ROUND_HALF_UP)


def _is_usd(currency):
    """True where a cost's currency is US dollars (#1557), as a clean boolean to group on.

    Only USD is split out. Every GP company Nexus serves keeps its books in CAD and buys in CAD or USD,
    so any other currency id would be a surprise rather than a case; it stays in the Canadian figure, as
    everything did before the split, rather than growing a figure per currency nobody uses."""
    return func.coalesce(func.upper(func.trim(currency)), "") == USD


# A project row's cost currency: its PO's when it is priced off a PO line - the PO is the truth there,
# and a row received before cost_currency existed has it null - else the row's own. Every read below
# that prices a project row outer-joins the PO line and its PO for this.
_ROW_IS_USD = _is_usd(func.coalesce(POModel.currency, InventoryLocationModel.cost_currency))

# A staged product's unit price, split by currency (#1557): (Canadian share, US share). The two add up
# to the one blended price the page used before the split; each is the part of it paid in that
# currency, so a staged quantity times each share is the staged value in that currency.
_Price = tuple[Decimal, Decimal]


# --- the two stored rows, get-or-created so a fresh company never renders empty -------------------


def get_settings(session: Session, company: str) -> InventoryValueSettings:
    """The company's AVERAGE DOOR COST row, created at zero on first read.

    The caller commits; the create is flushed here so the resolver can serialize the row it just
    made - the same shape po_document_settings_repository.get_settings uses for its singleton.
    """
    settings = session.get(InventoryValueSettings, company)
    if settings is not None:
        return settings
    # #1201: insert-if-absent, not check-then-insert. Two first reads at once (two tabs, two people)
    # both found nothing, both inserted, and the loser hit the primary key as a masked server error
    # on a plain page load.
    session.execute(
        pg_insert(InventoryValueSettings)
        .values(company=company, average_door_cost=_ZERO)
        .on_conflict_do_nothing(index_elements=["company"])
    )
    return session.get(InventoryValueSettings, company, populate_existing=True)


def get_general_row(session: Session, company: str) -> DoorsOnHand:
    """The company's general DOORS ON HAND row - the doors belonging to no job - created at zero.

    It exists whether or not anybody has typed a number into it, because the page shows it as a line
    of the table rather than as something you add. A company with no general row would render a table
    whose first row is missing and whose GENERAL STOCK figure silently omits doors.
    """
    stmt = select(DoorsOnHand).where(DoorsOnHand.company == company, DoorsOnHand.project_id.is_(None))
    row = session.scalars(stmt).first()
    if row is not None:
        return row
    # #1201: the same insert-if-absent as get_settings, against the partial unique index that allows
    # one general row per company.
    session.execute(
        pg_insert(DoorsOnHand)
        .values(id=uuid.uuid4(), company=company, project_id=None, quantity=0)
        .on_conflict_do_nothing(index_elements=["company"], index_where=text("project_id IS NULL"))
    )
    return session.scalars(stmt.execution_options(populate_existing=True)).one()


# --- the computed halves --------------------------------------------------------------------------


def _shelf_value_by_project(session: Session, company: str) -> dict[tuple[uuid.UUID, bool], Decimal]:
    """Hardware on the shelves, per (project, priced in USD), at the same coalesce every value view in
    this codebase applies: the PO line's cost, else the row's own off-PO cost (the SharePoint
    migration), else 0.

    The full `quantity` counts, deficient units included - that is what the warehouse dashboard's
    total-value tile shows, and two screens naming the same thing must not answer differently.
    Archived projects are included: archiving hides a job from the pickers, it does not empty its
    racks (#637).
    """
    rows = session.execute(
        select(
            InventoryLocationModel.project_id,
            _ROW_IS_USD,
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
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .join(Project, InventoryLocationModel.project_id == Project.id)
        .where(Project.company == company)
        .group_by(InventoryLocationModel.project_id, _ROW_IS_USD)
    ).all()
    return {(row[0], bool(row[1])): Decimal(row[2] or 0) for row in rows}


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


def _picked_cost_rows(
    session: Session,
    company: str | None,
    *,
    project_id: uuid.UUID | None = None,
    hardware_category: str | None = None,
    product_code: str | None = None,
):
    """The priced APPLIED pick lines per (project, category, code): the Canadian and US cost sums and
    the quantity behind each. The read `_picked_unit_costs` documents, narrowable to one project's
    product for a write path that prices a single combo (#1952)."""
    effective_cost = func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost)
    line_cost = PullPickLine.quantity * effective_cost
    stmt = (
        select(
            PullRequestModel.project_id,
            PullPickLine.hardware_category,
            PullPickLine.product_code,
            func.coalesce(func.sum(case((_ROW_IS_USD, None), else_=line_cost)), 0),
            func.coalesce(func.sum(case((_ROW_IS_USD, line_cost), else_=None)), 0),
            func.coalesce(func.sum(case((_ROW_IS_USD, None), else_=PullPickLine.quantity)), 0),
            func.coalesce(func.sum(case((_ROW_IS_USD, PullPickLine.quantity), else_=None)), 0),
        )
        .select_from(PullPickLine)
        .join(PullRequestModel, PullPickLine.pull_request_id == PullRequestModel.id)
        .join(InventoryLocationModel, PullPickLine.inventory_location_id == InventoryLocationModel.id)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
        .join(Project, PullRequestModel.project_id == Project.id)
        .where(
            PullPickLine.state == PullPickLineState.APPLIED,
            # #1939: a pull still in progress has its picked units on the cart, priced by the same lines.
            or_(
                and_(
                    PullRequestModel.source == PullRequestSource.SHIPPING_OUT,
                    PullRequestModel.status == PullRequestStatus.COMPLETED,
                ),
                PullRequestModel.status == PullRequestStatus.IN_PROGRESS,
            ),
            effective_cost.is_not(None),
        )
        .group_by(PullRequestModel.project_id, PullPickLine.hardware_category, PullPickLine.product_code)
    )
    if company is not None:
        stmt = stmt.where(Project.company == company)
    if project_id is not None:
        stmt = stmt.where(PullRequestModel.project_id == project_id)
    if hardware_category is not None:
        stmt = stmt.where(PullPickLine.hardware_category == hardware_category)
    if product_code is not None:
        stmt = stmt.where(PullPickLine.product_code == product_code)
    return session.execute(stmt).all()


def _picked_unit_costs(session: Session, company: str) -> dict[tuple[uuid.UUID, str, str], _Price]:
    """What the staged units actually cost, read off the rows they were picked from.

    Staged hardware has left the shelf, so there is no inventory row left to price it by - but there
    IS a record of exactly which rows it came off: the APPLIED pick lines (#367). Those rows are kept
    at quantity 0 and keep their cost, so walking the pick line back to its row recovers the price of
    the very units on the cart. Quantity-weighted, because one pull can take the same product off two
    rows bought at different prices.

    Lines whose row has been deleted (`inventory_location_id` is ON DELETE SET NULL) and lines whose
    row knows no cost are skipped rather than counted at zero - a missing price is not a free door
    closer, and the project-average fallback below is a better answer than 0.

    Each pick line's cost is in the currency of the row it came off (#1557), so the quantity-weighted
    price is split into a Canadian and a US share over the same total quantity.
    """
    costs: dict[tuple[uuid.UUID, str, str], _Price] = {}
    for project_id, category, code, cad_sum, usd_sum, cad_qty, usd_qty in _picked_cost_rows(session, company):
        qty_sum = cad_qty + usd_qty
        if not qty_sum:
            continue
        costs[(project_id, category, code)] = (
            Decimal(cad_sum) / Decimal(qty_sum),
            Decimal(usd_sum) / Decimal(qty_sum),
        )
    return costs


def picked_unit_price(
    session: Session, project_id: uuid.UUID, hardware_category: str, product_code: str
) -> tuple[Decimal, str | None] | None:
    """What one project's product cost as it was picked, as (cost, `cost_currency`), or None when no
    priced pick line knows (#1952). The same lines that price staged hardware here, so a shipped unit
    that comes back is worth what it was worth on the cart, not whatever the project's newest row cost.

    A row holds one currency, so a product picked in both prices in the one most of its units were
    picked in, at that currency's own quantity-weighted cost; a tie stays Canadian.
    """
    rows = _picked_cost_rows(
        session, None, project_id=project_id, hardware_category=hardware_category, product_code=product_code
    )
    if not rows:
        return None
    _, _, _, cad_sum, usd_sum, cad_qty, usd_qty = rows[0]
    if usd_qty > cad_qty:
        return Decimal(usd_sum) / Decimal(usd_qty), USD
    if cad_qty:
        return Decimal(cad_sum) / Decimal(cad_qty), None
    return None


def _project_average_costs(
    session: Session, keys: list[tuple[uuid.UUID, str, str]]
) -> dict[tuple[uuid.UUID, str, str], _Price]:
    """The fallback price for a staged product with no priced pick line behind it - hardware picked
    before #367, or picked off rows that have since been deleted.

    A plain average over the project's inventory rows for that product, zero-quantity rows included:
    a row emptied by the very pick being priced is the most relevant row there is, so weighting by
    what is left on the shelf would discard exactly the evidence wanted. Rows that know no cost are
    ignored by `avg` rather than dragging the answer toward zero.

    Narrowed to the projects and products that actually need a fallback, so the statement stays one
    grouped read of a handful of groups rather than every combo the company has ever held.

    The average is split by currency the way the picked price is (#1557): each share is the sum of that
    currency's costs over the count of every known cost, so the two still add up to the plain average.
    """
    if not keys:
        return {}
    effective_cost = func.coalesce(POLineItemModel.unit_cost, InventoryLocationModel.unit_cost)
    rows = session.execute(
        select(
            InventoryLocationModel.project_id,
            InventoryLocationModel.hardware_category,
            InventoryLocationModel.product_code,
            func.coalesce(func.sum(case((_ROW_IS_USD, None), else_=effective_cost)), 0),
            func.coalesce(func.sum(case((_ROW_IS_USD, effective_cost), else_=None)), 0),
            func.count(effective_cost),
        )
        .select_from(InventoryLocationModel)
        .outerjoin(POLineItemModel, InventoryLocationModel.po_line_item_id == POLineItemModel.id)
        .outerjoin(POModel, POLineItemModel.po_id == POModel.id)
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
    return {
        (pid, cat, code): (Decimal(cad_sum) / count, Decimal(usd_sum) / count)
        for pid, cat, code, cad_sum, usd_sum, count in rows
        if count
    }


def _staged_value_by_project(session: Session, company: str) -> dict[tuple[uuid.UUID, bool], Decimal]:
    """Staged hardware per (project, priced in USD) - the same keying as the shelf.

    Units picked for a pull still in progress are counted here too (#1939): the pick took them off the
    shelf, so they are not in the shelf value, and they are not staged until the pull is handed over -
    but they are still in the building, on the cart, priced the same way as staged units.
    """
    staged = _staged_quantities(session, company)
    for row in session.execute(warehouse.in_pick_stmt(company=company, by_project=True)):
        key = (row.project_id, row.hardware_category, row.product_code)
        staged[key] = staged.get(key, 0) + int(row.in_pick or 0)
    if not staged:
        return {}
    picked = _picked_unit_costs(session, company)
    fallback = _project_average_costs(session, [key for key in staged if key not in picked])

    value: dict[tuple[uuid.UUID, bool], Decimal] = defaultdict(Decimal)
    for key, quantity in staged.items():
        # #1951: a picked price is what the units cost, 0 included - a row bought at a known $0 is free
        # hardware, not an unknown one. Only a product with no priced pick line takes the average.
        price = picked[key] if key in picked else fallback.get(key) or (_ZERO, _ZERO)
        cad_share, usd_share = price
        value[(key[0], False)] += Decimal(quantity) * cad_share
        value[(key[0], True)] += Decimal(quantity) * usd_share
    return dict(value)


def _stock_pool_value(session: Session, company: str) -> dict[tuple[PoolKind, bool], Decimal]:
    """The jobless pool, per (kind, priced in USD) (#832, #1557), priced off the rows' own off-PO cost -
    the same expression the warehouse dashboard's stock tile uses - in the rows' own `cost_currency`,
    since a pool row has no PO to read one from. Stock scopes through its WAREHOUSE, never a project
    (#637). One grouped statement; a kind with no rows is zero."""
    is_usd = _is_usd(StockItemModel.cost_currency)
    rows = session.execute(
        select(
            StockItemModel.kind,
            is_usd,
            func.coalesce(func.sum(StockItemModel.quantity * func.coalesce(StockItemModel.unit_cost, 0)), 0),
        )
        .select_from(StockItemModel)
        .join(Warehouse, StockItemModel.warehouse_id == Warehouse.id)
        .where(Warehouse.company == company)
        .group_by(StockItemModel.kind, is_usd)
    ).all()
    values = {(kind, usd): _ZERO for kind in PoolKind for usd in (False, True)}
    for kind, usd, total in rows:
        values[(kind, bool(usd))] = Decimal(total or 0)
    return values


# --- the page ------------------------------------------------------------------------------------


def _empty_bucket() -> dict:
    return {
        "hardware_value": _ZERO,
        "door_count": 0,
        "door_value": _ZERO,
        "total_value": _ZERO,
        "usd_hardware_value": _ZERO,
    }


def _hardware_field(is_usd: bool) -> str:
    """Which of a bucket's two hardware figures a value belongs in (#1557)."""
    return "usd_hardware_value" if is_usd else "hardware_value"


def get_inventory_value(session: Session, company: str) -> dict:
    """The whole INVENTORY VALUE page for one GP company, in seven statements plus the two get-or-creates.

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
    buckets = {
        OSSA: _empty_bucket(),
        NON_OSSA: _empty_bucket(),
        GENERAL_STOCK: _empty_bucket(),
        OVERHEAD: _empty_bucket(),
    }

    # Hardware. Every project of the company falls in exactly one of the two project buckets, and a
    # project with no rows at all contributes nothing rather than being skipped as unknown.
    # US-dollar hardware goes to its own figure and never into the Canadian one (#1557).
    for (project_id, is_usd), value in list(shelf.items()) + list(staged.items()):
        bucket = OSSA if ossa_flags.get(project_id) else NON_OSSA
        buckets[bucket][_hardware_field(is_usd)] += value
    pool = _stock_pool_value(session, company)
    for is_usd in (False, True):
        buckets[GENERAL_STOCK][_hardware_field(is_usd)] = pool[(PoolKind.STOCK, is_usd)]
        buckets[OVERHEAD][_hardware_field(is_usd)] = pool[(PoolKind.OVERHEAD, is_usd)]

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
        bucket["usd_hardware_value"] = _cents(bucket["usd_hardware_value"])
        bucket["door_value"] = _cents(Decimal(bucket["door_count"]) * average_door_cost)
        # Summed from the rounded halves so the caption ("hardware $X + doors $Y") always adds up to
        # the figure printed above it. Canadian dollars only: the USD figure is shown beside it.
        bucket["total_value"] = bucket["hardware_value"] + bucket["door_value"]

    return {
        "company": company,
        "ossa": buckets[OSSA],
        "non_ossa": buckets[NON_OSSA],
        "general_stock": buckets[GENERAL_STOCK],
        "overhead": buckets[OVERHEAD],
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

    # #1473: insert-if-absent, as #1201 made the settings and general rows. Two first saves of one
    # project at once (two tabs, two people adding it) both found nothing and both inserted, and the
    # loser hit uq_doors_on_hand_company_project as a masked server error. The row is then locked and
    # set, so the later save's number is the one kept.
    session.execute(
        pg_insert(DoorsOnHand)
        .values(id=uuid.uuid4(), company=company, project_id=project_id, quantity=quantity)
        .on_conflict_do_nothing(constraint="uq_doors_on_hand_company_project")
    )
    row = session.scalars(
        select(DoorsOnHand)
        .where(DoorsOnHand.company == company, DoorsOnHand.project_id == project_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).one()
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
    cents = _cents(Decimal(amount))
    # #1211: the column is Numeric(12, 2), ten digits ahead of the point. Checked after rounding, so a
    # figure that rounds up past the column is refused here rather than overflowing at commit as a
    # masked server error.
    if cents >= _MAX_DOOR_COST:
        raise ValidationError("Average door cost must be less than $10,000,000,000.", field="amount")
    settings = get_settings(session, company)
    settings.average_door_cost = cents
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
    else:
        # #1608: the demo company is offered only to a caller working in it.
        stmt = stmt.where(Project.company != DEMO_COMPANY)
    return sorted(c for c in session.scalars(stmt).all() if c)
