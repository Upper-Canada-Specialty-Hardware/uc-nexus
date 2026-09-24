"""Repository for project CRUD operations."""

import json
import logging
import uuid
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import (
    ConflictError,
    GpJobNotOpenError,
    GpSetupInvalidError,
    NotFoundError,
    RelayCallError,
    ValidationError,
)
from app.models.enums import GpJobState
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel

logger = logging.getLogger(__name__)


def list_projects_with_opening_counts(
    session: Session, *, company: str | None = None, include_archived: bool = True
) -> list[tuple[ProjectModel, int]]:
    """All projects newest-first, each paired with its opening count from one grouped query -
    list views never lazy-load the openings relationship.

    `company` is the caller's tenant scope (#637); None means unscoped, which is the admin answer.
    `include_archived` is False for the picker every module reads and True for the admin page, which
    has to keep showing an archived project to un-archive it."""
    stmt = select(ProjectModel).order_by(ProjectModel.created_at.desc())
    if company is not None:
        stmt = stmt.where(ProjectModel.company == company)
    if not include_archived:
        stmt = stmt.where(ProjectModel.archived.is_(False))
    projects = list(session.scalars(stmt).unique().all())
    count_rows = session.execute(select(OpeningModel.project_id, func.count()).group_by(OpeningModel.project_id)).all()
    counts: dict[uuid.UUID, int] = {pid: c for pid, c in count_rows}
    return [(p, counts.get(p.id, 0)) for p in projects]


def get_project(session: Session, project_uuid: uuid.UUID, *, company: str | None = None) -> ProjectModel | None:
    project = session.get(ProjectModel, project_uuid)
    if project is not None and company is not None and project.company != company:
        return None
    return project


def get_project_by_schedule_id(
    session: Session, schedule_project_id: str, *, company: str | None = None
) -> ProjectModel | None:
    """Project by its TITAN schedule identity (the project_id column), openings eagerly loaded.

    A job number is only unique WITHIN a company since #637, so an unscoped lookup can now match more
    than one row - it returns the first, which is only correct for an admin who asked without a
    company. Every scoped caller passes one."""
    stmt = (
        select(ProjectModel)
        .options(selectinload(ProjectModel.openings))
        .where(ProjectModel.project_id == schedule_project_id)
    )
    if company is not None:
        stmt = stmt.where(ProjectModel.company == company)
    return session.scalars(stmt).unique().first()


def get_project_with_openings(session: Session, project_uuid: uuid.UUID) -> ProjectModel | None:
    stmt = select(ProjectModel).options(selectinload(ProjectModel.openings)).where(ProjectModel.id == project_uuid)
    return session.scalars(stmt).unique().first()


def adopt_gp_job(
    session: Session, job_number: str, job_name: str | None, company: str, *, record: dict | None = None
) -> ProjectModel:
    """Adopt a live GP job (JC00102) as a project. job_number becomes the project's identity
    (project_id, immutable). Raises ConflictError if this job has already been adopted.

    `record` is the relay's full job record (#730), passed only when the relay reports one: the new
    project then starts with every GP-held field filled in. Without it the project gets GP's job name
    and nothing else, which is all an older relay's list carries.

    `company` is the GP company the job was read from (#637) and is half of the project's identity:
    the already-adopted check is against (company, job_number), so TUBC 1001 and UCSH 1001 adopt as
    two projects rather than the second one being refused as a duplicate of the first."""
    # job_number is the project's identity, so normalize it (the old CreateProjectDialog trimmed
    # client-side; direct callers of this mutation don't). Blank/whitespace would create an
    # identity-less project, and an un-trimmed ' 1001 ' would dodge the already-adopted check.
    job_number = (job_number or "").strip()
    if not job_number:
        raise ValidationError("job_number is required", field="job_number")
    company = (company or "").strip().upper()
    if not company:
        raise ValidationError("company is required", field="company")
    existing = session.scalars(
        select(ProjectModel).where(ProjectModel.project_id == job_number, ProjectModel.company == company)
    ).first()
    if existing is not None:
        raise ConflictError(
            f"GP job {job_number} has already been adopted as a project in {company}",
            field="job_number",
        )

    project = ProjectModel(
        id=uuid.uuid4(),
        company=company,
        project_id=job_number,
        description=job_name,
    )
    if record is not None:
        apply_gp_job_record(project, record)
    session.add(project)
    session.flush()
    return project


# --- the GP job record (#730) ------------------------------------------------------------------------
# relay key -> project column, for the text fields GP owns. description, client and the site address
# are the columns that predate the mirror; the rest were added with it.
_GP_TEXT_FIELDS = {
    "job_name": "description",
    "customer_name": "client",
    "address1": "address",
    "address2": "address2",
    "city": "city",
    "state": "state",
    "zip_code": "zip",
    "country": "country",
    "customer_number": "customer_number",
    "job_address_code": "job_address_code",
    "billto_address_code": "billto_address_code",
    "division": "division",
    "tax_schedule_id": "tax_schedule_id",
    "use_tax_schedule_id": "use_tax_schedule_id",
    "estimator_id": "estimator_id",
    "estimator_name": "estimator_name",
    "ws_manager_id": "ws_manager_id",
    "ws_manager_name": "ws_manager_name",
}

_GP_DATE_FIELDS = {
    "closed_date": "gp_closed_date",
    "created_date": "gp_created_date",
    "schedule_start_date": "schedule_start_date",
    "scheduled_completion_date": "scheduled_completion_date",
    "bid_due_date": "bid_due_date",
}

_GP_MONEY_FIELDS = (
    "orig_contract_amount",
    "contract_to_date",
    "total_actual_cost",
    "billed_amount_ttd",
    "retention_amount_ttd",
    "net_billed_ttd",
)

_GP_JOB_STATES = {
    "active": GpJobState.ACTIVE,
    "inactive": GpJobState.INACTIVE,
    "closed": GpJobState.CLOSED,
}

# GP has no empty date: a date field nobody filled in holds 1900-01-01.
_GP_EMPTY_DATE = date(1900, 1, 1)


def _gp_text(value) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None


def _gp_date(value) -> date | None:
    """An ISO date (or datetime) off the wire, as a calendar date. GP's 1900-01-01 placeholder reads
    as no date: a job start date of 1900 on the project page would look like data."""
    if not value:
        return None
    try:
        parsed = date.fromisoformat(str(value)[:10])
    except ValueError:
        return None
    return None if parsed <= _GP_EMPTY_DATE else parsed


def _gp_money(value) -> Decimal | None:
    """A number or a numeric string - the relay may send either."""
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def apply_gp_job_record(project: ProjectModel, record: dict) -> None:
    """Overwrite a project's GP-held fields with GP's job record (#730). GP owns them, so the copy is
    overwritten, never compared - a value GP holds as empty empties it here too.

    Only keys PRESENT in the record are written. A record missing a key says nothing about that field,
    and blanking it would erase what the last complete read put there. The Nexus-only fields (project
    manager, job site name, contractor, application, the GC contact, OSSA, archived, the TITAN fields)
    are not in the maps above and are never touched.

    Seeing the job at all clears gp_missing_since. SQLAlchemy writes only the columns whose value
    actually moved, so an unchanged job costs no UPDATE and does not bump updated_at."""
    for key, column in _GP_TEXT_FIELDS.items():
        if key in record:
            setattr(project, column, _gp_text(record.get(key)))
    for key, column in _GP_DATE_FIELDS.items():
        if key in record:
            setattr(project, column, _gp_date(record.get(key)))
    for key in _GP_MONEY_FIELDS:
        if key in record:
            setattr(project, key, _gp_money(record.get(key)))
    state = _GP_JOB_STATES.get(str(record.get("gp_job_state") or "").strip().lower())
    if state is not None:
        project.gp_job_state = state
    project.gp_missing_since = None


def note_jobs_missing_from_gp(
    session: Session, company: str, seen: set[str], pass_started_at: datetime
) -> dict[str, list[str]]:
    """Record - and on the second consecutive pass, act on - this company's projects whose job was in
    neither of GP's job tables on a complete read (#730). Returns {"marked": [...], "not_in_gp": [...]}.

    The two-pass rule is the GP-DELETED PO RULE's, for the same reason: one read cannot tell a deleted
    job from one caught mid-edit, so the first miss only stamps gp_missing_since with the pass's start,
    and a later pass that misses it again marks it NOT_IN_GP. Its GP-held fields keep their last values,
    which are the last thing GP said about the job. A job that reappears clears the stamp through
    apply_gp_job_record and takes GP's state again.

    `seen` must come from a SUCCESSFUL, complete list_jobs read; the caller guarantees that. Caller
    commits."""
    stmt = select(ProjectModel).where(ProjectModel.company == company)
    if seen:
        stmt = stmt.where(ProjectModel.project_id.notin_(list(seen)))
    marked: list[str] = []
    not_in_gp: list[str] = []
    for project in session.scalars(stmt).all():
        if project.gp_job_state == GpJobState.NOT_IN_GP:
            continue
        if project.gp_missing_since is None:
            project.gp_missing_since = pass_started_at
            marked.append(project.project_id)
        elif project.gp_missing_since < pass_started_at:
            project.gp_job_state = GpJobState.NOT_IN_GP
            not_in_gp.append(project.project_id)
    session.flush()
    return {"marked": sorted(marked), "not_in_gp": sorted(not_in_gp)}


_REFUSAL_STATES = {
    "job_inactive": GpJobState.INACTIVE,
    "job_closed": GpJobState.CLOSED,
    "job_not_registered": GpJobState.NOT_IN_GP,
}


def gp_job_not_open_error(job_number: str | None, state: GpJobState) -> GpJobNotOpenError:
    """The one wording for a write refused because of where the job stands in GP, whichever side
    caught it."""
    job = f"GP job {job_number}" if job_number else "This purchase order's GP job"
    if state == GpJobState.INACTIVE:
        return GpJobNotOpenError(
            f"{job} is inactive in GP, so nothing can be written into GP against it. "
            f"The job has to be made active again in GP first."
        )
    if state == GpJobState.CLOSED:
        return GpJobNotOpenError(f"{job} is closed in GP, so nothing can be written into GP against it.")
    return GpJobNotOpenError(f"{job} is not in GP, so nothing can be written into GP against it.")


def gp_job_refusal(e: RelayCallError, job_number: str | None = None) -> GpJobNotOpenError | None:
    """The relay's live refusal of a write because of the job (job_inactive, job_closed,
    job_not_registered) as the same error the up-front check raises, or None for any other refusal.

    Read from the relay's error body the way job_already_exists is. The relay's own context names the
    job when the caller does not know it - a receipt carries only the PO number."""
    detail = e.detail or {}
    state = _REFUSAL_STATES.get(str(detail.get("error") or ""))
    if state is None:
        return None
    if not job_number:
        context = detail.get("context")
        if isinstance(context, dict):
            job_number = _gp_text(context.get("job_number"))
    return gp_job_not_open_error(job_number, state)


def require_gp_job_open(session: Session, project_id: uuid.UUID | None) -> None:
    """Refuse a NEXUS TO GP WRITE naming a job GP will not take one against (#730): inactive, closed,
    or not in GP.

    Modelled on require_gp_setup_ok and called where a GP write starts - PO REGISTRATION, GP RECEIVE
    ENTRY and a job edit that changes a GP field - and nowhere that stays inside Nexus. It is the clean
    up-front message; the relay checks the job live as well, and its refusal maps to the same error.

    NULL (never mirrored) and ACTIVE pass. NULL is what every project looks like against an older
    relay, and refusing on it would stop every write until the workstation updates. project_id None
    (a stock PO) is a no-op."""
    if project_id is None:
        return
    row = session.execute(
        select(ProjectModel.project_id, ProjectModel.gp_job_state).where(ProjectModel.id == project_id)
    ).first()
    if row is None or row.gp_job_state in (None, GpJobState.ACTIVE):
        return
    raise gp_job_not_open_error(row.project_id, row.gp_job_state)


def parse_gp_setup_issues(detail: str | None) -> list[dict]:
    """The {cost_code, account_index} pairs out of a project's gp_setup_detail column (#425).

    Tolerant on purpose. The column is JSON text written by the sync from whatever the relay reported,
    and it is read on every project query and in every quarantine message - a malformed or
    old-shaped value must degrade to "broken, details unavailable" rather than 500 the project list.
    Anything unparseable, or not a list of objects, yields []."""
    if not detail:
        return []
    try:
        parsed = json.loads(detail)
    except (TypeError, ValueError):
        logger.warning("gp_setup_detail is not valid JSON; treating as no detail")
        return []
    if not isinstance(parsed, list):
        return []
    return [
        {"cost_code": str(item.get("cost_code") or ""), "account_index": int(item.get("account_index") or 0)}
        for item in parsed
        if isinstance(item, dict)
    ]


def _describe_gp_setup_issues(issues: list[dict]) -> str:
    """The human half of the quarantine message: the cost codes and the accounts they point at.

    Capped at three because the point is recognition, not enumeration - the 62 affected production
    jobs average 24 broken codes each, and an error message listing all of them is one nobody reads."""
    if not issues:
        return "its GP cost codes point at general ledger accounts that do not exist in this company"
    shown = ", ".join(f"{i['cost_code']} -> GL account index {i['account_index']}" for i in issues[:3])
    if len(issues) > 3:
        shown += f", and {len(issues) - 3} more"
    return f"these cost codes point at general ledger accounts that do not exist in this company: {shown}"


def require_gp_setup_ok(session: Session, project_id: uuid.UUID | None) -> None:
    """Refuse to act on a project whose GP job setup is known broken (#425).

    The single server-side quarantine gate, called by every action that would put work into GP or
    commit hardware to a job: schedule import / Start a Request (finalize_import_session), registering a
    PO, receiving against one, and confirming a shipment. It is server-side because the frontend
    banner is a courtesy - a stale tab, a replayed mutation or a direct GraphQL call must hit the same
    wall.

    Only `gp_setup_ok is False` blocks. None (never checked) and True both pass:
      - None is what a project looks like before the first sync pass reaches it, and while no relay is
        connected at all. Quarantining on None would let a relay outage freeze every project in Nexus,
        including the actions that never touch GP.
      - the stamp can be stale by up to one poll interval, which is why register_po_in_gp additionally
        re-checks the job LIVE at submit time. This gate is the floor, not the ceiling.

    project_id None is a no-op: a draft PO with no project has no GP job to be broken."""
    if project_id is None:
        return
    row = session.execute(
        select(ProjectModel.project_id, ProjectModel.gp_setup_ok, ProjectModel.gp_setup_detail).where(
            ProjectModel.id == project_id
        )
    ).first()
    if row is None or row.gp_setup_ok is not False:
        return
    issues = parse_gp_setup_issues(row.gp_setup_detail)
    raise GpSetupInvalidError(
        f"GP job {row.project_id} is not set up correctly, so this project is on hold: "
        f"{_describe_gp_setup_issues(issues)}. A purchase order on this job would register in GP but "
        f"could never be received. Accounting has to correct the job's cost-code accounts in GP "
        f"before work on this project can continue.",
        issues=issues,
    )


def stamp_gp_setup_health(session: Session, verdicts: dict[str, dict], company: str) -> int:
    """Record the relay's per-job GP setup verdict on every project it covers (#425). Returns how many
    projects were stamped. The caller commits.

    `verdicts` is keyed by GP job number, which is the project's `project_id`, and each value is the
    relay's {ok, issues} for that job. `company` scopes the update (#637): a job number is only unique
    within a company, so an unscoped stamp would write one company's verdict onto another company's
    project of the same number. Projects GP did not report are left ALONE rather than reset to
    null: a job filtered out of the answer (the single-job re-check, a job deleted in GP) says nothing
    about whether its setup was fine an hour ago, and blanking the verdict would silently un-quarantine
    a broken project.

    One UPDATE per changed project inside the caller's transaction, and the whole thing is skipped for
    a project whose verdict has not moved - the sync runs every five minutes over ~900 projects, and
    rewriting an unchanged row 900 times per pass would churn the table for nothing. checked_at is
    stamped on every pass though, changed or not: "last confirmed" is the useful reading of it."""
    now = datetime.utcnow()
    stamped = 0
    projects = session.scalars(
        select(ProjectModel).where(
            ProjectModel.project_id.in_(list(verdicts)),
            ProjectModel.company == (company or "").strip().upper(),
        )
    ).all()
    for project in projects:
        verdict = verdicts.get(project.project_id)
        if verdict is None:
            continue
        ok = bool(verdict.get("ok"))
        issues = verdict.get("issues") or []
        # Serialized here rather than by the caller so the shape parse_gp_setup_issues expects is
        # decided in exactly one place.
        detail = json.dumps(
            [
                {"cost_code": str(i.get("cost_code") or ""), "account_index": int(i.get("account_index") or 0)}
                for i in issues
                if isinstance(i, dict)
            ]
        )
        project.gp_setup_ok = ok
        project.gp_setup_detail = detail if issues else None
        project.gp_setup_checked_at = now
        stamped += 1
    session.flush()
    return stamped


def update_project(
    session: Session,
    project_id: uuid.UUID,
    description: str | None = None,
    client: str | None = None,
    job_site_name: str | None = None,
    address: str | None = None,
    city: str | None = None,
    state: str | None = None,
    zip: str | None = None,
    contractor: str | None = None,
    project_manager: str | None = None,
    application: str | None = None,
    gc_contact_name: str | None = None,
    gc_phone: str | None = None,
    gc_email: str | None = None,
    off_site_storage_agreement: bool | None = None,
) -> ProjectModel:
    """Update editable project fields. project_id and TITAN refs are immutable.

    Any argument left as None is not changed; pass an empty string to clear a text field.
    """
    project = session.get(ProjectModel, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    if description is not None:
        project.description = description
    if client is not None:
        project.client = client
    if job_site_name is not None:
        project.job_site_name = job_site_name
    if address is not None:
        project.address = address
    if city is not None:
        project.city = city
    if state is not None:
        project.state = state
    if zip is not None:
        project.zip = zip
    if contractor is not None:
        project.contractor = contractor
    if project_manager is not None:
        project.project_manager = project_manager
    if application is not None:
        project.application = application
    if gc_contact_name is not None:
        project.gc_contact_name = gc_contact_name
    if gc_phone is not None:
        project.gc_phone = gc_phone
    if gc_email is not None:
        project.gc_email = gc_email
    if off_site_storage_agreement is not None:
        project.off_site_storage_agreement = off_site_storage_agreement

    session.flush()
    return project


def set_project_archived(session: Session, project_id: uuid.UUID, archived: bool) -> ProjectModel:
    """Hide a project from the picker every module reads, or bring it back (#637).

    Deliberately the whole of what archiving does. Its POs, inventory, pull requests and shipments are
    untouched and keep working - a job that is finished being STARTED is not a job whose history stops
    being readable, and a flag that also disabled work would be a lifecycle change nobody asked for."""
    project = session.get(ProjectModel, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")
    project.archived = archived
    session.flush()
    return project


def get_admin_project_detail(session: Session, project_id: uuid.UUID) -> dict | None:
    """The project plus the three rollups the admin Projects page shows when a row is opened (#637).

    One grouped aggregate per stat and no relationship walk (CLAUDE.md perf rules): a project with
    9,000 openings and 400 POs costs the same four queries as an empty one. Returns None when the
    project does not exist, which the resolver turns into a null.
    """
    from app.models.enums import PullRequestStatus, ShippingOutRequestStatus
    from app.models.inventory import InventoryLocation
    from app.models.pull_request import PullRequest
    from app.models.purchase_order import PurchaseOrder
    from app.models.shipping_out_request import ShippingOutRequest

    project = session.get(ProjectModel, project_id)
    if project is None:
        return None

    po_counts = session.execute(
        select(PurchaseOrder.status, func.count())
        .where(PurchaseOrder.project_id == project_id, PurchaseOrder.deleted_at.is_(None))
        .group_by(PurchaseOrder.status)
    ).all()

    on_hand = session.scalar(
        select(func.coalesce(func.sum(InventoryLocation.quantity), 0)).where(InventoryLocation.project_id == project_id)
    )

    # "Open" is the request AND the pull it minted: a rejected request is finished, and so is an
    # accepted one whose pull has been completed or cancelled - counting those would make the number
    # grow forever and say nothing about what is still in flight. One LEFT JOIN rather than a second
    # query, so the whole detail is still four reads.
    open_requests = session.scalar(
        select(func.count())
        .select_from(ShippingOutRequest)
        .outerjoin(PullRequest, PullRequest.id == ShippingOutRequest.pull_request_id)
        .where(
            ShippingOutRequest.project_id == project_id,
            ShippingOutRequest.status != ShippingOutRequestStatus.REJECTED,
            (PullRequest.id.is_(None))
            | (PullRequest.status.notin_([PullRequestStatus.COMPLETED, PullRequestStatus.CANCELLED])),
        )
    )

    return {
        "project": project,
        "po_counts_by_status": [(status, count) for status, count in po_counts],
        "inventory_on_hand": int(on_hand or 0),
        "open_shipping_request_count": int(open_requests or 0),
    }
