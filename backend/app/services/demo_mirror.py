"""What the demo company is built from (#1657): UBC, or in CI a made-up company.

Demo mode is one shared copy of UBC that everybody in it works in. A build (`demo_reset.reset`, run by
`demo_build`) wipes the demo company and builds it from a `Source`, which is everything the build needs
in one shape whichever company it came from:

  - jobs: the jobs the simulated GP starts with, which the job sync adopts as the demo's projects;
  - rows: the legacy inventory list (app/services/demo_snapshot.py), which becomes the warehouse;
  - masters: GP's masters the simulated GP answers with - vendors, customers, tax, cost codes;
  - open POs: POs already open in GP, copied once and the role-play's from then on;
  - schedules: hardware schedules the company has in Nexus, for the projects that have one.

`ubc_source` reads UBC as it is. Which jobs it takes was ruled on #1657: a job GP marks active, or one
the legacy list holds anything against - GP's inactive flag does not mean a job is done, and plenty of
inactive ones still hold stock. Its POs and schedules are read from UBC's own rows in Nexus, which the
GP PO mirror and the import keep current, so the build does not ask GP for them. Its masters are what
`read_gp_masters` last read from UBC's GP through the relay, and its rows what `read_legacy_list` last
read from SharePoint: both are stored (`demo_mirror_state`, `demo_inventory_snapshots`), a failed read
keeps the last good one, and the build never waits on GP or SharePoint being reachable.

`made_up_source` is the made-up company the demo was before #1657, with the scripted workflow states on
top (`made_up`): CI builds from it, so the build is tested end to end without any real data in the
repository. `DEMO_SOURCE=made-up` selects it; anything else builds from UBC.
"""

import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.database import SessionLocal
from app.demo import MIRROR_COMPANY
from app.errors import RelayCallError
from app.models.enums import GpJobState, POStatus
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import demo_mirror_state_repository as state
from app.repositories import demo_snapshot_repository, import_repository
from app.services import demo_gp, demo_snapshot

logger = logging.getLogger(__name__)

MADE_UP = "made-up"
UBC = "ubc"

# Who the stored legacy list says read it, for the admin page.
LEGACY_LIST_READER = "SharePoint (read automatically)"
LEGACY_LIST_NAME = "Legacy inventory list"

# The POs that are still open in GP: registered, confirmed or part received. A draft is not in GP at all.
_OPEN = (POStatus.GP_REGISTERED, POStatus.VENDOR_CONFIRMED, POStatus.PARTIALLY_RECEIVED)

# The POP line numbers GP gives a PO's lines, for a copied line the mirror recorded no number for.
_ORD_STEP = 16384


@dataclass
class Source:
    name: str
    jobs: list[dict]
    rows: list[demo_snapshot.SnapshotRow]
    masters: dict
    open_pos: list[dict] = field(default_factory=list)
    # Job number -> the schedule's openings and hardware, in the shapes the import's finalize takes.
    schedules: dict[str, dict] = field(default_factory=dict)
    # The made-up company's scripted workflow states run on top (demo_seed).
    made_up: bool = False

    @property
    def job_numbers(self) -> set[str]:
        return {j["job_number"] for j in self.jobs}


def configured() -> str:
    """Which company the demo is built from: UBC, unless `DEMO_SOURCE` says the made-up one."""
    return MADE_UP if os.getenv("DEMO_SOURCE", "").strip().lower() == MADE_UP else UBC


def load_source(session: Session, *, summary: bool = False) -> Source:
    """The source the demo is built from. `summary` is `ubc_source`'s: only for a reader that counts it."""
    return made_up_source(session) if configured() == MADE_UP else ubc_source(session, summary=summary)


# --- the made-up company -----------------------------------------------------------------------------


def made_up_source(session: Session) -> Source:
    """The made-up company, with the stored legacy list's jobs beside its own when one is stored."""
    rows = demo_snapshot_repository.rows(session)
    fixed = {job["job_number"] for job in demo_gp.JOBS}
    jobs = demo_gp.JOBS + [j for j in demo_snapshot.gp_jobs(rows) if j["job_number"] not in fixed]
    return Source(name=MADE_UP, jobs=jobs, rows=rows, masters=demo_gp.MADE_UP_MASTERS, made_up=True)


# --- UBC ---------------------------------------------------------------------------------------------


def mirrored(project: Project, holding: set[str]) -> bool:
    """Whether a UBC job is one of the demo's projects (ruled on #1657): GP marks it active, or the legacy
    list holds anything against it."""
    return project.gp_job_state == GpJobState.ACTIVE or project.project_id in holding


def ubc_source(session: Session, *, summary: bool = False) -> Source:
    """UBC as it is. `summary` is for the readers that only count what it holds or name its vendors and
    customers - the admin page's status, polled every few seconds while a build runs, and the GP masters
    read (#1833): it has no schedules, which are every opening and hardware row of every mirrored project,
    and its open POs are only their numbers and vendors, without their lines. Never for a build."""
    rows = demo_snapshot_repository.rows(session)
    holding = set(demo_snapshot.holding_jobs(rows))
    projects = [
        p
        for p in session.scalars(
            select(Project).where(Project.company == MIRROR_COMPANY).order_by(Project.project_id)
        ).all()
        if mirrored(p, holding)
    ]
    open_pos = _open_po_vendors(session) if summary else _open_pos(session)
    stored = state.get(session, state.GP_MASTERS) or {}
    return Source(
        name=UBC,
        jobs=[_job(p) for p in projects],
        rows=rows,
        masters=_masters(stored.get("masters"), open_pos),
        open_pos=open_pos,
        schedules={} if summary else _schedules(session, projects),
    )


def _job(project: Project) -> dict:
    """A UBC project as a job of the simulated GP: what GP holds for it, as the job sync last read it."""
    return {
        "job_number": project.project_id,
        "job_name": project.description,
        "gp_job_state": project.gp_job_state.value.lower() if project.gp_job_state else "active",
        "customer_number": project.customer_number,
        "customer_name": project.client,
        "job_address_code": project.job_address_code,
        "billto_address_code": project.billto_address_code,
        "address1": project.address,
        "address2": project.address2,
        "city": project.city,
        "state": project.state,
        "zip_code": project.zip,
        "country": project.country,
        "division": project.division,
        "tax_schedule_id": project.tax_schedule_id,
        "use_tax_schedule_id": project.use_tax_schedule_id,
        "estimator_id": project.estimator_id,
    }


def _open_po_filter() -> tuple:
    return (
        PurchaseOrder.gp_company == MIRROR_COMPANY,
        PurchaseOrder.status.in_(_OPEN),
        PurchaseOrder.po_number.is_not(None),
        PurchaseOrder.deleted_at.is_(None),
    )


def _open_pos(session: Session) -> list[dict]:
    """UBC's POs still open in GP, each as GP would read it back: its lines with what GP has received on
    them so far (`received_base`), so receipts in the demo count on from there. A PO with no lines is left
    out, as the GP PO mirror leaves out a read with none: there is nothing on it to receive."""
    pos = session.scalars(
        select(PurchaseOrder)
        .where(*_open_po_filter())
        .options(selectinload(PurchaseOrder.line_items))
        .order_by(PurchaseOrder.po_number)
    ).all()
    project_ids = {po.project_id for po in pos if po.project_id}
    jobs = (
        dict(session.execute(select(Project.id, Project.project_id).where(Project.id.in_(project_ids))).all())
        if project_ids
        else {}
    )
    out = []
    for po in pos:
        if not po.line_items:
            continue
        job = jobs.get(po.project_id)
        lines = sorted(po.line_items, key=lambda li: (li.gp_line_ord is None, li.gp_line_ord or 0, li.created_at))
        out.append(
            {
                "po_number": po.po_number,
                "gp_status": 1,
                "vendor_id": po.gp_vendor_id,
                "vendor_name": po.vendor_name_snapshot,
                "doc_date": (po.ordered_at or po.created_at.date()).isoformat(),
                "freight": float(po.shipping_cost or 0),
                # #1557: a UBC PO bought in US dollars stays one in the copy, so inventory value in demo
                # mode splits it out the way it does for UBC.
                "currency": po.currency or "CAD",
                "modified_at": datetime.utcnow().isoformat(),
                "source_table": "work",
                "idempotency_key": None,
                "lines": [
                    {
                        "ord": li.gp_line_ord or _ORD_STEP * (n + 1),
                        "item": li.hardware_category,
                        "itemdesc": li.product_code,
                        "unit_cost": float(li.unit_cost or 0),
                        "qty": float(li.ordered_quantity),
                        "qty_cancelled": 0.0,
                        "job": job if (li.job_cost and job) else None,
                        "line_status": 1,
                        "cost_code": li.cost_code,
                        "received_base": float(li.received_quantity or 0),
                    }
                    for n, li in enumerate(lines)
                ],
            }
        )
    return out


def _open_po_vendors(session: Session) -> list[dict]:
    """The POs `_open_pos` copies - open, with lines - as only their numbers and vendors, in its order: what a
    summary counts and names them by (#1833), in one query and without a line loaded."""
    has_lines = select(POLineItem.id).where(POLineItem.po_id == PurchaseOrder.id).exists()
    rows = session.execute(
        select(PurchaseOrder.po_number, PurchaseOrder.gp_vendor_id, PurchaseOrder.vendor_name_snapshot)
        .where(*_open_po_filter(), has_lines)
        .order_by(PurchaseOrder.po_number)
    ).all()
    return [{"po_number": n, "vendor_id": vendor_id, "vendor_name": name} for n, vendor_id, name in rows]


def _masters(read: dict | None, open_pos: list[dict]) -> dict:
    """The masters the simulated GP answers with: UBC's as last read, every vendor a copied PO names among
    them. Never read yet, the made-up masters stand in for the rest - the vendors still come from the POs,
    so every copied PO can be received."""
    masters = {**demo_gp.MADE_UP_MASTERS, **(read or {})}
    if not read:
        masters["vendors"] = []
    vendors = list(masters["vendors"])
    known = {v["vendor_id"] for v in vendors}
    for po in open_pos:
        vendor_id = po.get("vendor_id")
        if vendor_id and vendor_id not in known:
            known.add(vendor_id)
            vendors.append({"vendor_id": vendor_id, "vendor_name": po.get("vendor_name"), "currency": "CAD"})
    masters["vendors"] = vendors
    return masters


def _camel(name: str) -> str:
    head, *rest = name.split("_")
    return head + "".join(part.title() for part in rest)


_OPENING_FIELDS = (
    "opening_number",
    "building",
    "floor",
    "location",
    "location_to",
    "location_from",
    "hand",
    "width",
    "length",
    "door_thickness",
    "jamb_thickness",
    "door_type",
    "frame_type",
    "interior_exterior",
    "keying",
    "heading_no",
    "single_pair",
    "assignment_multiplier",
    "leaf_count",
)
_HARDWARE_FIELDS = (
    "opening_number",
    "product_code",
    "hardware_category",
    "item_quantity",
    "leaf",
    "unit_cost",
    "unit_price",
    "list_price",
    "vendor_discount",
    "markup_pct",
    "vendor_no",
    "manufacturer",
    "phase_code",
    "item_category_code",
    "product_group_code",
    "submittal_id",
)


def _schedules(session: Session, projects: list[Project]) -> dict[str, dict]:
    """The hardware schedules UBC has in Nexus for `projects`, in the shapes the import's finalize takes:
    the schedule as UBC imported it, before anybody ordered anything off it."""
    ids = [p.id for p in projects]
    if not ids:
        return {}
    with_hardware = set(
        session.scalars(select(HardwareItem.project_id).where(HardwareItem.project_id.in_(ids)).distinct())
    )
    out = {}
    for project in projects:
        if project.id not in with_hardware:
            continue
        data = import_repository.get_project_hardware_schedule(session, project.id)
        if not data:
            continue
        out[project.project_id] = {
            "openings": [{_camel(f): getattr(o, f) for f in _OPENING_FIELDS} for o in data["openings"]],
            "hardwareItems": [{_camel(f): item.get(f) for f in _HARDWARE_FIELDS} for item in data["hardware_items"]],
        }
    return out


def has_schedule(session: Session, project_id: uuid.UUID) -> bool:
    """Whether a project has a schedule on it: openings or hardware."""
    openings = session.scalar(select(func.count()).select_from(Opening).where(Opening.project_id == project_id))
    hardware = session.scalar(
        select(func.count()).select_from(HardwareItem).where(HardwareItem.project_id == project_id)
    )
    return bool(openings or hardware)


# --- reading UBC's GP and the legacy list -------------------------------------------------------------


def _list(result: dict | None, key: str) -> list:
    return list((result or {}).get(key) or [])


async def read_gp_masters() -> dict:
    """UBC's GP masters, read through the relay as the screens read them, paced like every other
    scheduled read. Per vendor and per customer only for the ones the demo uses: the vendors of UBC's
    open POs and the customers of its mirrored jobs, so a read is a few hundred calls at most. Stored
    under `gp_masters`; a failed read raises and leaves the stored ones as they were."""
    from app.services import gp_load

    async def call(op: str, payload: dict | None = None) -> dict:
        return (await gp_load.paced_call(MIRROR_COMPANY, op, payload, reads=1))["result"] or {}

    async def detail(op: str, payload: dict) -> dict:
        """One vendor's or customer's detail. A failed one is that vendor's or customer's detail missing,
        not the whole read lost: the simulated GP stands in a made-up address for it."""
        try:
            return await call(op, payload)
        except RelayCallError as e:
            logger.warning("demo mirror: %s %s could not be read: %s", op, payload, e)
            return {}

    with SessionLocal() as session:
        source = ubc_source(session, summary=True)
    vendor_ids = sorted({po["vendor_id"] for po in source.open_pos if po.get("vendor_id")})
    customers = sorted({j["customer_number"] for j in source.jobs if j.get("customer_number")})

    vendors = _list(await call("list_vendors"), "vendors")
    by_id = {v.get("vendor_id"): v for v in vendors}
    addresses: dict[str, list[dict]] = {}
    for vendor_id in vendor_ids:
        if vendor_id not in by_id:
            continue
        contact = await detail("get_vendor_contact", {"vendor_id": vendor_id})
        by_id[vendor_id] = {
            **by_id[vendor_id],
            "contact": contact.get("contact_name") or by_id[vendor_id].get("contact"),
            "email": contact.get("email"),
        }
        addresses[vendor_id] = _list(await detail("list_vendor_addresses", {"vendor_id": vendor_id}), "addresses")
    customer_addresses = {
        c: _list(await detail("list_customer_addresses", {"customer": c}), "addresses") for c in customers
    }
    divisions = _list(await call("list_divisions"), "divisions")
    cost_codes = {d: _list(await call("list_cost_code_master", {"division": d}), "cost_codes") for d in divisions}
    options = await call("list_po_entry_options")
    masters = {
        "vendors": list(by_id.values()),
        "vendor_addresses": addresses,
        "customers": _list(await call("list_customers"), "customers"),
        "customer_addresses": customer_addresses,
        "tax_details": _list(await call("list_tax_details"), "tax_details"),
        "tax_schedules": _list(await call("list_tax_schedules"), "tax_schedules"),
        "purchase_tax_schedules": _list(await call("list_purchase_tax_schedules"), "tax_schedules"),
        "divisions": divisions or demo_gp.DIVISIONS,
        "cost_code_master": cost_codes or demo_gp.MADE_UP_MASTERS["cost_code_master"],
        "employees": _list(await call("list_employees"), "employees"),
        "buyers": _list(await call("list_buyers_detailed"), "buyers"),
        "po_entry_options": {
            "shipping_methods": _list(options, "shipping_methods"),
            "sites": _list(options, "sites"),
            "units_of_measure": _list(options, "units_of_measure"),
        },
    }
    return masters


async def read_legacy_list() -> list[demo_snapshot.SnapshotRow]:
    from app.services import sharepoint_inventory

    return demo_snapshot.parse_list_items(await sharepoint_inventory.fetch_inventory_items())


async def refresh_legacy_list() -> str | None:
    """Read the legacy list again and store it; a failed read is recorded and the stored list stands.
    Seconds: one Graph read. Returns the error, or None."""
    if configured() == MADE_UP:
        return None
    attempted = datetime.utcnow().isoformat()
    try:
        rows = await read_legacy_list()
        # Stored even while a build runs: a build reads its source once, at its start (`load_source`).
        with SessionLocal() as session:
            demo_snapshot_repository.store(
                session, file_name=LEGACY_LIST_NAME, rows=rows, uploaded_by=LEGACY_LIST_READER
            )
            state.put(session, state.LEGACY_LIST, {"attempted_at": attempted, "error": None})
            session.commit()
        return None
    except Exception as e:  # noqa: BLE001 - recorded, and the stored list stands
        logger.exception("demo mirror: could not read the legacy inventory list")
        error = str(e) or type(e).__name__
        with SessionLocal() as session:
            state.put(session, state.LEGACY_LIST, {"attempted_at": attempted, "error": error})
            session.commit()
        return error


async def refresh_gp_masters() -> str | None:
    """Read UBC's GP masters again, store them, and give them to the simulated GP of the demo there is. A
    failed read is recorded and the stored masters stand. Long: the reads are paced behind every other
    scheduled GP read, so a build does not wait on this - it runs after (`demo_build`). Returns the
    error, or None."""
    if configured() == MADE_UP:
        return None
    attempted = datetime.utcnow().isoformat()
    with SessionLocal() as session:
        state.merge(session, state.GP_MASTERS, {"reading": True, "attempted_at": attempted})
        session.commit()
    try:
        masters = await read_gp_masters()
        with SessionLocal() as session:
            state.put(
                session,
                state.GP_MASTERS,
                {"masters": masters, "read_at": attempted, "attempted_at": attempted, "error": None, "reading": False},
            )
            # The demo there is answers with them from now on; the vendors its copied POs name stay in.
            if demo_gp.has_masters(session):
                demo_gp.update_masters(session, ubc_source(session, summary=True).masters)
            session.commit()
        return None
    except Exception as e:  # noqa: BLE001 - recorded, and the stored masters stand
        logger.exception("demo mirror: could not read UBC's GP masters")
        error = str(e) or type(e).__name__
        with SessionLocal() as session:
            state.merge(session, state.GP_MASTERS, {"attempted_at": attempted, "error": error, "reading": False})
            session.commit()
        return error


async def refresh_sources() -> dict:
    """Both reads, one after the other: the nightly sync's. Returns {list, masters}: each one's error, or
    None."""
    return {"list": await refresh_legacy_list(), "masters": await refresh_gp_masters()}
