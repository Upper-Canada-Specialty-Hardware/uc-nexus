"""Repository for project CRUD operations."""

import json
import logging
import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, GpSetupInvalidError, NotFoundError, ValidationError
from app.models.project import Opening as OpeningModel
from app.models.project import Project as ProjectModel

logger = logging.getLogger(__name__)


def list_projects_with_opening_counts(session: Session) -> list[tuple[ProjectModel, int]]:
    """All projects newest-first, each paired with its opening count from one grouped query -
    list views never lazy-load the openings relationship."""
    projects = list(session.scalars(select(ProjectModel).order_by(ProjectModel.created_at.desc())).unique().all())
    count_rows = session.execute(select(OpeningModel.project_id, func.count()).group_by(OpeningModel.project_id)).all()
    counts: dict[uuid.UUID, int] = {pid: c for pid, c in count_rows}
    return [(p, counts.get(p.id, 0)) for p in projects]


def get_project(session: Session, project_uuid: uuid.UUID) -> ProjectModel | None:
    return session.get(ProjectModel, project_uuid)


def get_project_by_schedule_id(session: Session, schedule_project_id: str) -> ProjectModel | None:
    """Project by its TITAN schedule identity (the project_id column), openings eagerly loaded."""
    stmt = (
        select(ProjectModel)
        .options(selectinload(ProjectModel.openings))
        .where(ProjectModel.project_id == schedule_project_id)
    )
    return session.scalars(stmt).unique().first()


def get_project_with_openings(session: Session, project_uuid: uuid.UUID) -> ProjectModel | None:
    stmt = select(ProjectModel).options(selectinload(ProjectModel.openings)).where(ProjectModel.id == project_uuid)
    return session.scalars(stmt).unique().first()


def adopt_gp_job(session: Session, job_number: str, job_name: str | None) -> ProjectModel:
    """Adopt a live GP job (JC00102) as a project. job_number becomes the project's identity
    (project_id, immutable); job_name is a snapshot of GP's job description at adopt time, not
    synced afterward. Raises ConflictError if this job has already been adopted."""
    # job_number is the project's identity, so normalize it (the old CreateProjectDialog trimmed
    # client-side; direct callers of this mutation don't). Blank/whitespace would create an
    # identity-less project, and an un-trimmed ' 1001 ' would dodge the already-adopted check.
    job_number = (job_number or "").strip()
    if not job_number:
        raise ValidationError("job_number is required", field="job_number")
    existing = session.scalars(select(ProjectModel).where(ProjectModel.project_id == job_number)).first()
    if existing is not None:
        raise ConflictError(
            f"GP job {job_number} has already been adopted as a project",
            field="job_number",
        )

    project = ProjectModel(
        id=uuid.uuid4(),
        project_id=job_number,
        description=job_name,
    )
    session.add(project)
    session.flush()
    return project


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


def stamp_gp_setup_health(session: Session, verdicts: dict[str, dict]) -> int:
    """Record the relay's per-job GP setup verdict on every project it covers (#425). Returns how many
    projects were stamped. The caller commits.

    `verdicts` is keyed by GP job number, which is the project's `project_id`, and each value is the
    relay's {ok, issues} for that job. Projects GP did not report are left ALONE rather than reset to
    null: a job filtered out of the answer (the single-job re-check, a job deleted in GP) says nothing
    about whether its setup was fine an hour ago, and blanking the verdict would silently un-quarantine
    a broken project.

    One UPDATE per changed project inside the caller's transaction, and the whole thing is skipped for
    a project whose verdict has not moved - the sync runs every five minutes over ~900 projects, and
    rewriting an unchanged row 900 times per pass would churn the table for nothing. checked_at is
    stamped on every pass though, changed or not: "last confirmed" is the useful reading of it."""
    now = datetime.utcnow()
    stamped = 0
    projects = session.scalars(select(ProjectModel).where(ProjectModel.project_id.in_(list(verdicts)))).all()
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
