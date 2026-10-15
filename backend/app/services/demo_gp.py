"""The demo company's GP, simulated in this process (#1608).

The relay gateway hands every call for the demo company here instead of putting it on the relay socket
(`RelayGateway.relay_call_with_meta`), so demo mode works with no relay connected and can never reach a
real GP. Each op answers in the shape the relay answers it in - the backend code that reads the answer
is the same code that reads a real one - and fails the way the relay fails, with a RelayCallError
carrying the relay's own error body.

What GP would remember is remembered in `demo_gp_records` (app/models/demo_gp_record.py): the jobs, the
POs registered into it, the receipts posted against them, buyers and customer addresses. The masters a
real company sets up once and rarely touches - vendors, customers, tax, cost codes, sites, employees -
are UBC's own (#1657): the build loads what it read from UBC's GP (`load`), and the simulated GP answers
with them. Nothing it answers with is ever written back to UBC's GP. Until a build has loaded any, the
made-up masters below stand in - and the made-up build (CI's) loads those.

A real GP refuses plenty of things this does not: it is a stand-in good enough to walk every workflow,
not a model of eConnect. The refusals it does make are the ones a user can reach from the screens, such
as a receipt for more than is still open on a line.
"""

import asyncio
from datetime import date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.database import SessionLocal
from app.demo import DEMO_BUYER_ID, DEMO_COMPANY, DEMO_COMPANY_NAME
from app.errors import RelayCallError
from app.models.demo_gp_record import DemoGpRecord

# --- the made-up masters ----------------------------------------------------------------------------

VENDORS = [
    {
        "vendor_id": "DEMOHAGER",
        "vendor_name": "Demo Hager Hinges",
        "vendor_class": "HARDWARE",
        "currency": "CAD",
        "contact": "Pat Hinge",
        "email": "orders@demo-hager.example.com",
    },
    {
        "vendor_id": "DEMOLCN",
        "vendor_name": "Demo LCN Closers",
        "vendor_class": "HARDWARE",
        "currency": "CAD",
        "contact": "Sam Closer",
        "email": "sales@demo-lcn.example.com",
    },
    {
        "vendor_id": "DEMOSCHLAGE",
        "vendor_name": "Demo Schlage Locks",
        "vendor_class": "HARDWARE",
        "currency": "USD",
        "contact": "Lee Lockwood",
        "email": "po@demo-schlage.example.com",
    },
    {
        "vendor_id": "DEMOVONDUP",
        "vendor_name": "Demo Von Duprin Exits",
        "vendor_class": "HARDWARE",
        "currency": "CAD",
        "contact": "Alex Exit",
        "email": None,
    },
    {
        "vendor_id": "DEMOIVES",
        "vendor_name": "Demo Ives Accessories",
        "vendor_class": "HARDWARE",
        "currency": "CAD",
        "contact": "Jordan Stop",
        "email": "orders@demo-ives.example.com",
    },
]

CUSTOMERS = [
    {"customer_number": "DEMOBUILD", "customer_name": "Demo Builders Ltd."},
    {"customer_number": "DEMOHOSP", "customer_name": "Demo General Hospital"},
    {"customer_number": "DEMOSCHOOL", "customer_name": "Demo District School Board"},
]

CUSTOMER_ADDRESSES = {
    "DEMOBUILD": [
        {"address_code": "PRIMARY", "city": "Toronto", "state": "ON"},
        {"address_code": "TOWER-A", "city": "Mississauga", "state": "ON"},
    ],
    "DEMOHOSP": [{"address_code": "PRIMARY", "city": "Hamilton", "state": "ON"}],
    "DEMOSCHOOL": [
        {"address_code": "PRIMARY", "city": "Ottawa", "state": "ON"},
        {"address_code": "EAST-HS", "city": "Kingston", "state": "ON"},
    ],
}

TAX_DETAILS = [
    {"tax_detail_id": "ON HST P", "description": "Ontario HST purchases", "percent": 13.0},
    {"tax_detail_id": "GST P", "description": "GST purchases", "percent": 5.0},
]

TAX_SCHEDULES = [
    {"tax_schedule_id": "ON HST", "description": "Ontario HST"},
    {"tax_schedule_id": "EXEMPT", "description": "Tax exempt"},
]

PURCHASE_TAX_SCHEDULES = [
    {"tax_schedule_id": "ON HST P", "description": "Ontario HST purchases", "details": [TAX_DETAILS[0]]},
]

DIVISIONS = ["DOORS", "HARDWARE"]

COST_CODE_MASTER = [
    {"cost_code": "210-100", "description": "Finish hardware", "cost_element": 2},
    {"cost_code": "210-200", "description": "Shop assembly", "cost_element": 2},
    {"cost_code": "210-300", "description": "Freight", "cost_element": 5},
]

EMPLOYEES = [
    {"employee_id": "DEMOEST1", "first_name": "Erin", "last_name": "Estimator"},
    {"employee_id": "DEMOPM1", "first_name": "Morgan", "last_name": "Manager"},
]

BUYERS = [
    {"buyer_id": DEMO_BUYER_ID, "description": "Demo buyer"},
    {"buyer_id": "DEMOPURCH", "description": "Demo purchasing"},
]

SHIPPING_METHODS = [
    {"id": "LOCAL DELIVERY", "description": "Local delivery"},
    {"id": "COURIER", "description": "Courier"},
    {"id": "PICKUP", "description": "Customer pickup"},
]

SITES = [
    {"code": "MAIN", "description": "Main warehouse"},
    {"code": "SHOP", "description": "Assembly shop"},
]

UNITS_OF_MEASURE = ["Each", "Pair", "Box"]

# The made-up masters as the build loads them: the shape `load` takes UBC's in.
MADE_UP_MASTERS = {
    "vendors": VENDORS,
    "vendor_addresses": {},
    "customers": CUSTOMERS,
    "customer_addresses": CUSTOMER_ADDRESSES,
    "tax_details": TAX_DETAILS,
    "tax_schedules": TAX_SCHEDULES,
    "purchase_tax_schedules": PURCHASE_TAX_SCHEDULES,
    "divisions": DIVISIONS,
    "cost_code_master": {division: COST_CODE_MASTER for division in DIVISIONS},
    "employees": EMPLOYEES,
    "buyers": BUYERS,
    "po_entry_options": {"shipping_methods": SHIPPING_METHODS, "sites": SITES, "units_of_measure": UNITS_OF_MEASURE},
}

# The made-up jobs the simulated GP starts with. The made-up build adopts them as the demo company's
# projects through the same job sync a real company's are adopted by.
JOBS = [
    {
        "job_number": "DEMO-1001",
        "job_name": "Demo Tower A",
        "customer_number": "DEMOBUILD",
        "job_address_code": "TOWER-A",
        "city": "Mississauga",
        "division": "DOORS",
    },
    {
        "job_number": "DEMO-1002",
        "job_name": "Demo Hospital Wing",
        "customer_number": "DEMOHOSP",
        "job_address_code": "PRIMARY",
        "city": "Hamilton",
        "division": "DOORS",
    },
    {
        "job_number": "DEMO-1003",
        "job_name": "Demo East High School",
        "customer_number": "DEMOSCHOOL",
        "job_address_code": "EAST-HS",
        "city": "Kingston",
        "division": "HARDWARE",
    },
    {
        "job_number": "DEMO-1004",
        "job_name": "Demo Office Retrofit",
        "customer_number": "DEMOBUILD",
        "job_address_code": "PRIMARY",
        "city": "Toronto",
        "division": "DOORS",
    },
]

# The POP line numbers GP gives a PO's lines: 16384, 32768, ... - the ord a receipt names a line by.
_ORD_STEP = 16384


# --- errors -------------------------------------------------------------------------------------------


def _refuse(code: str, message: str, **context) -> RelayCallError:
    """The relay's refusal for a call it could not run, in the relay's own error body."""
    return RelayCallError(message, detail={"error": code, "message": message, "context": context})


# --- records ------------------------------------------------------------------------------------------


def _get(session: Session, kind: str, key: str) -> DemoGpRecord | None:
    return session.scalars(select(DemoGpRecord).where(DemoGpRecord.kind == kind, DemoGpRecord.key == key)).first()


def _all(session: Session, kind: str) -> list[DemoGpRecord]:
    return list(
        session.scalars(
            select(DemoGpRecord).where(DemoGpRecord.kind == kind).order_by(DemoGpRecord.created_at, DemoGpRecord.key)
        )
    )


def _put(session: Session, kind: str, key: str, data: dict) -> DemoGpRecord:
    row = _get(session, kind, key)
    if row is None:
        row = DemoGpRecord(kind=kind, key=key, data=data)
        session.add(row)
    else:
        # A JSON column is only written back when the attribute is assigned a new object.
        row.data = dict(data)
    session.flush()
    return row


def _lock(session: Session, name: str) -> None:
    """Serialize the writes that mint a number, as GP serializes its own: two at once must not take the
    same one. Transaction-scoped, released when the caller commits."""
    session.execute(select(func.pg_advisory_xact_lock(func.hashtext(f"demo_gp:{name}"))))


def _next_number(session: Session, kind: str, prefix: str) -> str:
    count = session.scalar(select(func.count()).select_from(DemoGpRecord).where(DemoGpRecord.kind == kind)) or 0
    return f"{prefix}{count + 1:06d}"


def _masters(session: Session) -> dict:
    """The masters the simulated GP answers with: the ones the build loaded, or the made-up ones."""
    row = _get(session, "master", "masters")
    return {**MADE_UP_MASTERS, **row.data} if row else MADE_UP_MASTERS


def _employee_name(masters: dict, employee_id: str | None) -> str | None:
    employee = next((e for e in masters["employees"] if e.get("employee_id") == employee_id), None)
    if employee is None:
        return None
    return " ".join(p for p in (employee.get("first_name"), employee.get("last_name")) if p) or None


def _job_record(job: dict, masters: dict = MADE_UP_MASTERS) -> dict:
    """A job in the shape the relay's list_jobs reads one back in."""
    customer = next((c for c in masters["customers"] if c["customer_number"] == job.get("customer_number")), None)
    estimator_id = job.get("estimator_id") or "DEMOEST1"
    manager_id = job.get("ws_manager_id") or "DEMOPM1"
    return {
        "job_number": job["job_number"],
        "job_name": job.get("job_name"),
        "gp_job_state": job.get("gp_job_state") or "active",
        "closed_date": None,
        "closed_by": None,
        "customer_number": job.get("customer_number"),
        "customer_name": job.get("customer_name") or (customer["customer_name"] if customer else None),
        "job_address_code": job.get("job_address_code"),
        "billto_address_code": job.get("billto_address_code") or "PRIMARY",
        "address1": job.get("address1") or "100 Demo Street",
        "address2": None,
        "city": job.get("city"),
        "state": job.get("state") or "ON",
        "zip_code": job.get("zip_code") or "A1A 1A1",
        "country": job.get("country") or "Canada",
        "division": job.get("division") or masters["divisions"][0],
        "tax_schedule_id": job.get("tax_schedule_id") or "ON HST",
        "use_tax_schedule_id": job.get("use_tax_schedule_id"),
        "estimator_id": estimator_id,
        "estimator_name": _employee_name(masters, estimator_id),
        "ws_manager_id": manager_id,
        "ws_manager_name": _employee_name(masters, manager_id),
        "created_date": job.get("created_date") or "2026-09-01",
        "schedule_start_date": job.get("schedule_start_date"),
        "scheduled_completion_date": job.get("scheduled_completion_date"),
        "bid_due_date": job.get("bid_due_date"),
        "orig_contract_amount": 0.0,
        "contract_to_date": 0.0,
        "total_actual_cost": 0.0,
        "billed_amount_ttd": 0.0,
        "retention_amount_ttd": 0.0,
        "net_billed_ttd": 0.0,
    }


def _jobs(session: Session) -> list[dict]:
    """Every job. A build loads its jobs (`load`); before any has, the made-up ones are written in on first
    use, so a job update has a row to change - with the jobs the stored legacy list holds anything against
    (#1638)."""
    rows = _all(session, "job")
    if not rows and _get(session, "master", "masters") is None:
        # Under the job lock and read again: two first calls at once must not both write the fixed jobs.
        _lock(session, "job")
        rows = _all(session, "job")
    if not rows:
        from app.repositories import demo_snapshot_repository
        from app.services import demo_snapshot

        fixed = {job["job_number"] for job in JOBS}
        snapshot_jobs = demo_snapshot.gp_jobs(demo_snapshot_repository.rows(session))
        for job in JOBS + [j for j in snapshot_jobs if j["job_number"] not in fixed]:
            _put(session, "job", job["job_number"], _job_record(job))
        rows = _all(session, "job")
    return [r.data for r in rows]


def load(session: Session, *, masters: dict, jobs: list[dict], pos: list[dict]) -> None:
    """What a build starts the simulated GP with (#1657): the masters it answers with, the jobs the job sync
    adopts as projects, and POs already open in GP. Whatever it held is gone - the build wiped it. A
    PO's lines may say what was received before the copy (`received_base`); receipts count on top."""
    _put(session, "master", "masters", masters)
    for job in jobs:
        _put(session, "job", job["job_number"], _job_record(job, masters))
    for po in pos:
        _put(session, "po", po["po_number"], po)


def has_masters(session: Session) -> bool:
    """Whether a build has loaded masters: there is a demo to give fresh ones to."""
    return _get(session, "master", "masters") is not None


def update_masters(session: Session, masters: dict) -> None:
    """A fresh read of the masters for the demo there is (#1657). The caller commits."""
    _put(session, "master", "masters", masters)


def add_jobs(session: Session, jobs: list[dict]) -> list[str]:
    """Jobs that are not in the simulated GP yet, added as GP would add them (#1657): the nightly sync's.
    Returns the numbers added. The caller commits."""
    _lock(session, "job")
    masters = _masters(session)
    known = {j["job_number"] for j in _jobs(session)}
    added = []
    for job in jobs:
        if job["job_number"] not in known:
            _put(session, "job", job["job_number"], _job_record(job, masters))
            added.append(job["job_number"])
    return added


def _vendor(session: Session, vendor_id: str) -> dict:
    vendor = next((v for v in _masters(session)["vendors"] if v["vendor_id"] == (vendor_id or "").strip()), None)
    if vendor is None:
        raise _refuse("vendor_not_found", f"Vendor '{vendor_id}' does not exist in {DEMO_COMPANY}", vendor_id=vendor_id)
    return vendor


def _received(session: Session) -> dict[str, dict[int, float]]:
    """What every receipt has received, by PO number and line ord - read once for a whole answer."""
    received: dict[str, dict[int, float]] = {}
    for receipt in _all(session, "receipt"):
        by_ord = received.setdefault(receipt.data.get("po_number"), {})
        for line in receipt.data.get("lines") or []:
            ord_ = int(line["po_line_ord"])
            by_ord[ord_] = by_ord.get(ord_, 0.0) + float(line["quantity"])
    return received


def _po_with_receipts(po: dict, received: dict[str, dict[int, float]]) -> dict:
    """A PO as the relay reads it back: its lines, each with what has been received against it - what a
    copied PO had received in GP before it was copied, and the receipts posted here since."""
    by_ord = received.get(po["po_number"]) or {}
    lines = []
    for ln in po["lines"]:
        line = {k: v for k, v in ln.items() if k != "received_base"}
        line["received"] = float(ln.get("received_base") or 0) + by_ord.get(int(ln["ord"]), 0.0)
        lines.append(line)
    return {**po, "lines": lines}


_NO_ADDRESS = {
    "code": "PRIMARY",
    "contact": None,
    "address1": "1 Supplier Way",
    "address2": None,
    "address3": None,
    "city": "Toronto",
    "state": "ON",
    "postal_code": "M1M 1M1",
    "country": "Canada",
    "phone": None,
}


def _vendor_addresses(session: Session, vendor: dict) -> list[dict]:
    """A vendor's addresses: UBC's own where the build read them, one made-up address otherwise."""
    addresses = _masters(session)["vendor_addresses"].get(vendor["vendor_id"])
    return addresses or [{**_NO_ADDRESS, "contact": vendor.get("contact")}]


# --- the ops ------------------------------------------------------------------------------------------


def _list_vendors(session: Session, payload: dict) -> dict:
    return {
        "company": DEMO_COMPANY,
        "vendors": [
            {
                "vendor_id": v["vendor_id"],
                "vendor_name": v.get("vendor_name"),
                "vendor_class": v.get("vendor_class"),
                "status": v.get("status", 1),
                "currency": v.get("currency") or "CAD",
                "shipping_method": v.get("shipping_method") or "LOCAL DELIVERY",
                "purchase_address_code": v.get("purchase_address_code") or "PRIMARY",
                "contact": v.get("contact"),
            }
            for v in _masters(session)["vendors"]
        ],
    }


def _get_vendor_contact(session: Session, payload: dict) -> dict:
    vendor = _vendor(session, payload.get("vendor_id"))
    return {
        "company": DEMO_COMPANY,
        "vendor_id": vendor["vendor_id"],
        "vendor_name": vendor.get("vendor_name"),
        "contact_name": vendor.get("contact"),
        "email": vendor.get("email"),
    }


def _list_vendor_addresses(session: Session, payload: dict) -> dict:
    vendor = _vendor(session, payload.get("vendor_id"))
    return {"company": DEMO_COMPANY, "vendor_id": vendor["vendor_id"], "addresses": _vendor_addresses(session, vendor)}


def _list_po_entry_options(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, **_masters(session)["po_entry_options"]}


def _buyers(session: Session) -> list[dict]:
    """The masters' buyers, with the demo buyer everybody registers as always among them."""
    buyers = list(_masters(session)["buyers"])
    if not any(b.get("buyer_id") == DEMO_BUYER_ID for b in buyers):
        buyers.insert(0, BUYERS[0])
    return buyers + [r.data for r in _all(session, "buyer")]


def _list_buyers(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "buyers": [b["buyer_id"] for b in _buyers(session)]}


def _list_buyers_detailed(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "buyers": _buyers(session)}


def _create_buyer(session: Session, payload: dict) -> dict:
    buyer_id = (payload.get("buyer_id") or "").strip().upper()
    if not buyer_id:
        raise _refuse("invalid_payload", "buyer_id is required")
    if any(b["buyer_id"] == buyer_id for b in _buyers(session)):
        raise _refuse("buyer_already_exists", f"Buyer '{buyer_id}' already exists in {DEMO_COMPANY}", buyer_id=buyer_id)
    description = (payload.get("description") or "").strip() or None
    _put(session, "buyer", buyer_id, {"buyer_id": buyer_id, "description": description})
    return {"company": DEMO_COMPANY, "buyer_id": buyer_id, "description": description}


def _list_tax_details(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "tax_details": _masters(session)["tax_details"]}


def _list_tax_schedules(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "tax_schedules": _masters(session)["tax_schedules"]}


def _list_purchase_tax_schedules(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "tax_schedules": _masters(session)["purchase_tax_schedules"]}


def _cost_codes(session: Session, division: str | None) -> list[dict]:
    """A division's cost code master; a division the masters have none for takes the first one's."""
    by_division = _masters(session)["cost_code_master"]
    if division and division in by_division:
        return by_division[division]
    return next(iter(by_division.values()), [])


def _list_cost_codes(session: Session, payload: dict) -> dict:
    """A job's cost codes. A job set up in GP carries its division's codes, so those are its codes here."""
    job = (payload.get("job") or "").strip()
    if not job:
        raise _refuse("missing_job", "job is required")
    record = next((j for j in _jobs(session) if j["job_number"] == job), None)
    codes = _cost_codes(session, record.get("division") if record else None)
    return {"company": DEMO_COMPANY, "job": job, "cost_codes": codes}


def _list_cost_code_master(session: Session, payload: dict) -> dict:
    division = (payload.get("division") or "").strip()
    if not division:
        raise _refuse("missing_division", "division is required")
    return {"company": DEMO_COMPANY, "division": division, "cost_codes": _cost_codes(session, division)}


def _list_jobs(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "jobs": _jobs(session)}


def _job_setup_health(session: Session, payload: dict) -> dict:
    known = {j["job_number"] for j in _jobs(session)}
    if "jobs" in payload:
        asked = [str(j).strip() for j in payload.get("jobs") or [] if str(j).strip()]
        single = None
    else:
        single = (payload.get("job") or "").strip() or None
        asked = [single] if single else sorted(known)
    divisions = {j["job_number"]: j.get("division") for j in _jobs(session)}
    jobs = [
        {"job_number": j, "ok": True, "active_cost_code_count": len(_cost_codes(session, divisions[j])), "issues": []}
        for j in asked
        if j in known
    ]
    return {"company": DEMO_COMPANY, "job": single, "jobs": jobs}


def _list_customers(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "customers": _masters(session)["customers"]}


def _customer_addresses(session: Session, customer: str) -> list[dict]:
    created = [r.data for r in _all(session, "customer_address") if r.data.get("customer") == customer]
    return _masters(session)["customer_addresses"].get(customer, []) + [
        {"address_code": a["address_code"], "city": a.get("city"), "state": a.get("state")} for a in created
    ]


def _list_customer_addresses(session: Session, payload: dict) -> dict:
    customer = (payload.get("customer") or "").strip()
    if not customer:
        raise _refuse("missing_customer", "customer is required")
    return {"company": DEMO_COMPANY, "customer": customer, "addresses": _customer_addresses(session, customer)}


def _create_customer_address(session: Session, payload: dict) -> dict:
    customer = str(payload.get("customer") or payload.get("customer_number") or "").strip()
    if not customer:
        raise _refuse("missing_customer", "customer is required")
    code = str(payload.get("address_code") or "").strip().upper()
    if not code:
        raise _refuse("invalid_payload", "address_code is required")
    if any(a["address_code"] == code for a in _customer_addresses(session, customer)):
        raise _refuse(
            "address_already_exists", f"Customer '{customer}' already has an address '{code}'", address_code=code
        )
    address = {"address_code": code, "city": payload.get("city"), "state": payload.get("state")}
    _put(session, "customer_address", f"{customer}|{code}", {"customer": customer, **address})
    return {"company": DEMO_COMPANY, "customer": customer, "address": address}


def _list_divisions(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "divisions": _masters(session)["divisions"]}


def _list_employees(session: Session, payload: dict) -> dict:
    return {"company": DEMO_COMPANY, "employees": _masters(session)["employees"]}


def _create_job(session: Session, payload: dict) -> dict:
    job_number = str(payload.get("job_number") or "").strip()
    if not job_number:
        raise _refuse("invalid_payload", "job_number is required")
    _lock(session, "job")
    if any(j["job_number"] == job_number for j in _jobs(session)):
        raise _refuse(
            "job_already_exists", f"Job '{job_number}' already exists in {DEMO_COMPANY}", job_number=job_number
        )
    fields = {k: v for k, v in payload.items() if v is not None and not isinstance(v, (list, dict))}
    record = _job_record(
        {**fields, "job_number": job_number, "created_date": str(payload.get("created_date") or "")}, _masters(session)
    )
    _put(session, "job", job_number, record)
    return {
        "job_number": job_number,
        "job_name": record["job_name"],
        "company": DEMO_COMPANY,
        "cost_codes_provisioned": len(payload.get("cost_codes") or []),
        "record": record,
    }


def _job_row(session: Session, job_number: str) -> DemoGpRecord:
    _jobs(session)
    row = _get(session, "job", (job_number or "").strip())
    if row is None:
        raise _refuse("job_not_found", f"Job '{job_number}' does not exist in {DEMO_COMPANY}", job_number=job_number)
    return row


def _update_job(session: Session, payload: dict) -> dict:
    row = _job_row(session, payload.get("job_number"))
    changes = {k: v for k, v in payload.items() if k != "job_number" and v is not None}
    for key in ("schedule_start_date", "scheduled_completion_date", "bid_due_date"):
        if key in changes:
            changes[key] = str(changes[key])
    record = {**row.data, **changes}
    _put(session, "job", row.key, record)
    return {"job": record}


def _update_job_site(session: Session, payload: dict) -> dict:
    row = _job_row(session, payload.get("job_number"))
    record = dict(row.data)
    for key in ("job_name", "city", "state", "zip_code", "country"):
        if payload.get(key) is not None:
            record[key] = payload[key]
    address_code = (payload.get("address_code") or "").strip().upper() or record.get("job_address_code")
    record["job_address_code"] = address_code
    _put(session, "job", row.key, record)
    return {
        "job_number": row.key,
        "job_name": record.get("job_name"),
        "company": DEMO_COMPANY,
        "address_code": address_code,
        "address_created": False,
    }


def _create_po(session: Session, payload: dict) -> dict:
    header = payload.get("header") or {}
    lines = payload.get("lines") or []
    if not lines:
        raise _refuse("invalid_payload", "a PO needs at least one line")
    vendor = _vendor(session, header.get("vendor_id"))
    _lock(session, "po")
    key = (payload.get("idempotency_key") or "").strip() or None
    if key is not None:
        for row in _all(session, "po"):
            if row.data.get("idempotency_key") == key:
                return _po_response(row.data, existing=True)
    known_jobs = {j["job_number"] for j in _jobs(session)}
    for line in lines:
        job = (line.get("job_number") or "").strip()
        if job and job not in known_jobs:
            raise _refuse("job_not_found", f"Job '{job}' does not exist in {DEMO_COMPANY}", job_number=job)

    po_number = (payload.get("po_number") or "").strip() or _next_number(session, "po", "DPO")
    if payload.get("po_number_suffix"):
        po_number = f"{po_number}-{payload['po_number_suffix']}"
    if _get(session, "po", po_number) is not None:
        raise _refuse("po_already_exists", f"PO '{po_number}' already exists in {DEMO_COMPANY}", po_number=po_number)
    doc_date = str(header.get("doc_date") or date.today().isoformat())
    po = {
        "po_number": po_number,
        "gp_status": 1,
        "vendor_id": vendor["vendor_id"],
        "vendor_name": vendor.get("vendor_name"),
        "currency": header.get("currency_id") or vendor.get("currency") or "CAD",
        "doc_date": doc_date,
        "freight": float(header.get("freight_amount") or 0),
        "modified_at": datetime.utcnow().isoformat(),
        "source_table": "work",
        "idempotency_key": key,
        "lines": [
            {
                "ord": _ORD_STEP * (i + 1),
                "item": line.get("item_number"),
                "itemdesc": line.get("item_description"),
                "unit_cost": float(line.get("unit_cost") or 0),
                "qty": float(line.get("quantity") or 0),
                "qty_cancelled": 0.0,
                "job": (line.get("job_number") or "").strip() or None,
                "line_status": 1,
                "cost_code": line.get("cost_code"),
            }
            for i, line in enumerate(lines)
        ],
    }
    _put(session, "po", po_number, po)
    return _po_response(po, existing=False)


def _po_response(po: dict, *, existing: bool) -> dict:
    subtotal = sum(ln["qty"] * ln["unit_cost"] for ln in po["lines"])
    return {
        "po_number": po["po_number"],
        "company": DEMO_COMPANY,
        "lines_created": len(po["lines"]),
        "subtotal": round(subtotal, 2),
        "doc_date": po["doc_date"],
        "vendor_id": po["vendor_id"],
        "currency": po.get("currency") or "CAD",
        "tax_amount": 0.0,
        "existing": existing,
    }


def _create_receipt(session: Session, payload: dict) -> dict:
    po_number = (payload.get("po_number") or "").strip()
    lines = payload.get("lines") or []
    if not lines:
        raise _refuse("invalid_payload", "a receipt needs at least one line")
    _lock(session, "receipt")
    key = (payload.get("idempotency_key") or "").strip() or None
    if key is not None:
        for row in _all(session, "receipt"):
            if row.data.get("idempotency_key") == key:
                return {**_receipt_response(row.data), "existing": True}
    po_row = _get(session, "po", po_number)
    if po_row is None:
        raise _refuse("po_not_found", f"PO '{po_number}' does not exist in {DEMO_COMPANY}", po_number=po_number)
    po = _po_with_receipts(po_row.data, _received(session))
    by_ord = {int(ln["ord"]): ln for ln in po["lines"]}
    for line in lines:
        target = by_ord.get(int(line.get("po_line_ord") or 0))
        if target is None:
            raise _refuse("po_line_not_found", f"PO '{po_number}' has no line {line.get('po_line_ord')}")
        open_qty = target["qty"] - target["qty_cancelled"] - target["received"]
        if float(line.get("quantity") or 0) > open_qty + 1e-9:
            raise _refuse(
                "over_receipt",
                f"Line {target['ord']} of PO '{po_number}' has {open_qty:g} still to receive",
                po_number=po_number,
                ord=target["ord"],
            )
    receipt_number = _next_number(session, "receipt", "DRCT")
    receipt = {
        "receipt_number": receipt_number,
        "batch_number": f"{payload.get('batch_prefix') or 'EC'}DEMO",
        "po_number": po_number,
        "idempotency_key": key,
        "lines": [{"po_line_ord": int(ln["po_line_ord"]), "quantity": float(ln["quantity"])} for ln in lines],
    }
    _put(session, "receipt", receipt_number, receipt)
    return _receipt_response(receipt)


def _receipt_response(receipt: dict) -> dict:
    return {
        "receipt_number": receipt["receipt_number"],
        "batch_number": receipt["batch_number"],
        "po_number": receipt["po_number"],
        "company": DEMO_COMPANY,
        "lines_received": len(receipt["lines"]),
        "custom_db_written": False,
        "existing": False,
    }


def _read_pos_by_number(session: Session, payload: dict) -> dict:
    asked = [str(n).strip() for n in payload.get("po_numbers") or [] if str(n).strip()]
    pos, missing = [], []
    received = _received(session)
    for number in asked:
        row = _get(session, "po", number)
        if row is None:
            missing.append(number)
        else:
            pos.append(_strip(_po_with_receipts(row.data, received)))
    return {"company": DEMO_COMPANY, "pos": pos, "missing": missing}


def _sync_pos(session: Session, payload: dict) -> dict:
    received = _received(session)
    return {
        "company": DEMO_COMPANY,
        "pos": [_strip(_po_with_receipts(r.data, received)) for r in _all(session, "po")],
        "next_cursor": None,
    }


def _strip(po: dict) -> dict:
    """A stored PO without the bookkeeping the relay does not send."""
    return {k: v for k, v in po.items() if k not in ("idempotency_key", "currency")}


def _read_po_totals(session: Session, payload: dict) -> dict:
    po_number = (payload.get("po_number") or "").strip()
    if not po_number:
        raise _refuse("missing_po_number", "po_number is required")
    row = _get(session, "po", po_number)
    if row is None:
        return {"company": DEMO_COMPANY, "totals": None}
    po = row.data
    vendor = _vendor(session, po["vendor_id"])
    subtotal = sum(ln["qty"] * ln["unit_cost"] for ln in po["lines"])
    where = _vendor_addresses(session, vendor)[0]
    address = {
        "name": vendor.get("vendor_name"),
        "contact": where.get("contact") or vendor.get("contact"),
        **{k: where.get(k) for k in ("address1", "address2", "address3", "city", "state", "postal_code", "country")},
    }
    return {
        "company": DEMO_COMPANY,
        "totals": {
            "po_number": po_number,
            "subtotal": round(subtotal, 2),
            "freight": po.get("freight") or 0.0,
            "miscellaneous": 0.0,
            "tax_amount": 0.0,
            "trade_discount": 0.0,
        },
        "header": {
            "shipping_method": "LOCAL DELIVERY",
            "vendor_address_code": where.get("code") or "PRIMARY",
            "buyer_id": DEMO_BUYER_ID,
            "currency": po.get("currency") or "CAD",
            "vendor_address": address,
            "ship_to_code": "MAIN",
            "ship_to": {**address, "name": DEMO_COMPANY_NAME, "address1": "100 Demo Street"},
        },
    }


def _server_load(session: Session, payload: dict) -> dict:
    return {"sql_cpu_pct": 0.0, "other_cpu_pct": 0.0, "runnable_tasks": 0, "sampled_at": None, "source": "simulated"}


_OPS = {
    "list_vendors": _list_vendors,
    "get_vendor_contact": _get_vendor_contact,
    "list_vendor_addresses": _list_vendor_addresses,
    "list_po_entry_options": _list_po_entry_options,
    "list_buyers": _list_buyers,
    "list_buyers_detailed": _list_buyers_detailed,
    "create_buyer": _create_buyer,
    "list_tax_details": _list_tax_details,
    "list_tax_schedules": _list_tax_schedules,
    "list_purchase_tax_schedules": _list_purchase_tax_schedules,
    "list_cost_codes": _list_cost_codes,
    "list_cost_code_master": _list_cost_code_master,
    "list_jobs": _list_jobs,
    "job_setup_health": _job_setup_health,
    "list_customers": _list_customers,
    "list_customer_addresses": _list_customer_addresses,
    "create_customer_address": _create_customer_address,
    "list_divisions": _list_divisions,
    "list_employees": _list_employees,
    "create_job": _create_job,
    "update_job": _update_job,
    "update_job_site": _update_job_site,
    "create_po": _create_po,
    "create_receipt": _create_receipt,
    "read_pos_by_number": _read_pos_by_number,
    "sync_pos": _sync_pos,
    "read_po_totals": _read_po_totals,
    "server_load": _server_load,
}

OPS = frozenset(_OPS)


def call_sync(op: str, payload: dict) -> dict:
    """Run one op against the simulated GP, committing what it wrote. Raises RelayCallError as the
    relay does: `unknown_op` for an op it has no answer for, the op's own refusal otherwise."""
    handler = _OPS.get(op)
    if handler is None:
        raise _refuse("unknown_op", f"unknown op '{op}'", op=op)
    with SessionLocal() as session:
        try:
            result = handler(session, payload)
            session.commit()
            return result
        except Exception:
            session.rollback()
            raise


async def call(op: str, payload: dict) -> dict:
    """call_sync off the event loop, which the relay socket's read loop runs on."""
    return await asyncio.to_thread(call_sync, op, payload)


def wipe(session: Session) -> int:
    """Forget everything the simulated GP was told, for a reset. The caller commits."""
    return session.query(DemoGpRecord).delete(synchronize_session=False)
