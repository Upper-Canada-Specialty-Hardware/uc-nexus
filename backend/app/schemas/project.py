"""Project queries + mutations."""

import asyncio
import logging
import uuid

import strawberry

from app.auth import tenant_scope
from app.database import SessionLocal
from app.errors import (
    ConflictError,
    NotFoundError,
    RelayCallError,
    ValidationError,
    validation_error_from_relay,
)
from app.repositories import project_repository, tenancy
from app.services import gp_job_sync
from app.services.relay_gateway import JOB_MIRROR_FEATURE
from app.services.relay_gateway import gateway as relay_gateway

from .converters import project_to_type
from .inputs import CreateGpJobInput, UpdateProjectInput
from .relay import resolve_gp_company
from .types import (
    AdminProjectDetail,
    CreateGpJobResult,
    GpJobSyncResult,
    POStatusCount,
    Project,
    ProjectShipTo,
)

logger = logging.getLogger(__name__)


def _load_project(job_number: str, company: str) -> Project:
    with SessionLocal() as session:
        project = project_repository.get_project_by_schedule_id(session, job_number, company=company)
        if project is None:
            raise NotFoundError(f"Project {job_number} not found")
        return project_to_type(project)


async def _adopt_existing(job_number: str, company: str) -> Project:
    """Make sure a job GP already holds has its Nexus project, and return it.

    Runs a full sync pass rather than adopting the one job: the pass reads GP's own job master, so the
    project gets GP's name rather than whatever the caller typed, and it is the same code path that
    would have created this project a few minutes later anyway."""
    await gp_job_sync.run_once()
    return await asyncio.to_thread(_load_project, job_number.strip(), company)


@strawberry.type
class ProjectQueries:
    @strawberry.field
    def projects(self, info: strawberry.Info) -> list[Project]:
        """The project picker every module reads, so signed-in rather than the admin requirement on
        `admin_projects` below - same rows, fewer fields.

        Archived projects are excluded here and only here (#637): this is the list that decides what a
        user can start new work against, and a finished job should stop appearing in it without any of
        its existing POs, inventory or shipments changing behaviour."""
        with SessionLocal() as session:
            rows = project_repository.list_projects_with_opening_counts(
                session, company=tenant_scope(info), include_archived=False
            )
            return [project_to_type(p, include_openings=False, opening_count=count) for p, count in rows]

    @strawberry.field
    def admin_projects(self, info: strawberry.Info) -> list[Project]:
        """The Tenant Owner module's project list, with all editable fields.

        Includes archived rows - the page is where archiving is undone, so hiding them would make an
        archived project unreachable - and covers the caller's own company, or every company for the
        unscoped UC NEXUS ADMIN."""
        with SessionLocal() as session:
            rows = project_repository.list_projects_with_opening_counts(
                session, company=tenant_scope(info), include_archived=True
            )
            return [project_to_type(p, include_openings=False, opening_count=count) for p, count in rows]

    @strawberry.field
    def project_by_schedule_id(self, info: strawberry.Info, project_id: str) -> Project | None:
        with SessionLocal() as session:
            p = project_repository.get_project_by_schedule_id(session, project_id, company=tenant_scope(info))
            if p is None:
                return None
            return project_to_type(p)

    @strawberry.field
    def admin_project_detail(self, info: strawberry.Info, id: strawberry.ID) -> AdminProjectDetail | None:
        """What the Tenant Owner module's Projects page shows when a row is opened (#637) - the
        project plus the three rollups that answer "is anything still live on this job" before
        somebody archives it.

        Scoped by id (#729). It used to assume an unscoped caller, which was true while the only
        role that could reach it was exempt from the tenant line; a TENANT OWNER is not, so another
        company's project reads as absent here exactly as it does everywhere else."""
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            detail = project_repository.get_admin_project_detail(session, uuid.UUID(str(id)))
            if detail is None:
                return None
            return AdminProjectDetail(
                project=project_to_type(detail["project"], include_openings=False),
                po_counts_by_status=[
                    POStatusCount(status=status, count=count) for status, count in detail["po_counts_by_status"]
                ],
                inventory_on_hand=detail["inventory_on_hand"],
                open_shipping_request_count=detail["open_shipping_request_count"],
            )

    @strawberry.field
    def project_ship_to(self, info: strawberry.Info, project_id: strawberry.ID) -> ProjectShipTo | None:
        """The job-site address block for a project, by its UUID - the "deliver to site" ship-to option
        on the generated PO document (issue #230). A lean projection, kept off the PO list query."""
        with SessionLocal() as session:
            p = project_repository.get_project(session, uuid.UUID(str(project_id)), company=tenant_scope(info))
            if p is None:
                return None
            return ProjectShipTo(
                id=strawberry.ID(str(p.id)),
                project_id=p.project_id,
                job_site_name=p.job_site_name,
                address=p.address,
                city=p.city,
                state=p.state,
                zip=p.zip,
            )


@strawberry.type
class ProjectMutations:
    @strawberry.mutation
    async def create_gp_job(self, info: strawberry.Info, input: CreateGpJobInput) -> CreateGpJobResult:
        """Originate a job in GP, then hold it as a UC Nexus project (#380).

        This replaces the old adopt_gp_job mutation. Adoption is no longer something a user does: the
        gp_job_sync service creates a project for every job GP reports, so a manual adopt dialog could
        only ever land on "already adopted". What was missing was the other direction - Nexus could
        take a job GP already had, but could not originate one.

        GP goes first and there is no outbox fallback, unlike the PO and receive writes. Two reasons:
        the form cannot even be composed without live GP reads (customer, address codes, tax schedule
        and division all come from GP, the same gating the register-PO dialog applies), so a queued
        submit could never have been assembled while the relay was down; and a failed submit costs
        nothing to retry from the still-open dialog. Queuing would buy latency tolerance nobody needs
        and add an ambiguous-write class that does not otherwise exist here.

        The selected cost codes are provisioned in the SAME GP transaction as the job (#448), because
        the proc alone leaves JC00701 empty - a job with no cost codes has an empty register-PO
        dropdown and is quarantined by the #425 setup check on the next sync stamp. Splitting them
        into a second call would make that broken state reachable through a partial failure.

        `cost_codes_provisioned` carries how many of them GP actually kept, so the dialog can be honest
        about a selection that did not land. On the adopt path it is zero and means it: an already
        existing job is left exactly as GP has it, the picked codes are NOT applied to it, and
        created=false plus the zero count is how the client is told that.

        A tenant owner's action. Creating a job writes to the accounting system of record.

        `input.company` names the GP company the job is created in and becomes the project's tenant
        (#637). It is validated against the connected relay's enrolled companies and, for a scoped
        caller, against their own - which since #729 is the ordinary case, because a TENANT OWNER is
        pinned to one company and only the UC NEXUS ADMIN is not.
        """

        company = resolve_gp_company(info, input.company)

        payload = {
            "job_number": input.job_number,
            "job_name": input.job_name,
            "division": input.division,
            "customer_number": input.customer_number,
            "job_address_code": input.job_address_code,
            "billto_address_code": input.billto_address_code,
            "tax_schedule_id": input.tax_schedule_id,
            "created_date": input.created_date.isoformat(),
            "estimator_id": input.estimator_id,
            "ws_manager_id": input.ws_manager_id,
            "ws_project_number": input.ws_project_number,
            "bill_customer_number": input.bill_customer_number,
            "use_tax_schedule": input.use_tax_schedule,
            "schedule_start_date": input.schedule_start_date.isoformat() if input.schedule_start_date else None,
            "scheduled_completion_date": (
                input.scheduled_completion_date.isoformat() if input.scheduled_completion_date else None
            ),
            "bid_due_date": input.bid_due_date.isoformat() if input.bid_due_date else None,
            # Only the code number and its element travel (#448). Everything else the JC00701 row
            # needs - alias, description, and the GL account index above all - the relay reads out of
            # GP's own master inside the same transaction, so nothing here can dictate an account.
            "cost_codes": [
                {"cost_code": c.cost_code.strip(), "cost_element": c.cost_element} for c in input.cost_codes
            ],
        }

        try:
            result = await relay_gateway.relay_call(company, "create_job", payload)
        except RelayCallError as e:
            if (e.detail or {}).get("error") == "job_already_exists":
                # GP has the job but we were not the ones who put it there, OR we were and the reply
                # was lost (a relay_call timeout after the proc committed). Either way the invariant
                # this feature exists to hold - a job in GP is a project in Nexus - is satisfiable
                # right now, so satisfy it instead of dead-ending the dialog on an error that no
                # amount of retrying can clear.
                logger.info("create_gp_job: %s already in GP; adopting instead", input.job_number)
                project = await _adopt_existing(input.job_number, company)
                # Nothing was provisioned: the create never ran, and this path deliberately does not
                # go on to write cost codes onto a job somebody else's setup already owns.
                return CreateGpJobResult(project=project, created=False, cost_codes_provisioned=0)
            # GP said no - a closed fiscal period, an address code that isn't on the customer, a
            # division without accounts. The proc words those better than we could, so the message is
            # passed through to the dialog rather than replaced with a generic failure.
            raise validation_error_from_relay(e) from e

        # GP's own record of what it created, read back from JC00102 by the relay - not the input
        # echoed back (see ops.create_job_op).
        job_number = str((result or {}).get("job_number") or input.job_number).strip()
        job_name = str((result or {}).get("job_name") or input.job_name).strip() or None
        # The relay's verified read-back of JC00701, not len(payload["cost_codes"]). A relay older than
        # #448 ignores the unknown cost_codes key entirely and answers without this field, so it reads
        # as 0 - which is exactly what happened in GP, and how a silently dropped selection surfaces to
        # the dialog instead of being reported as a provisioned job.
        cost_codes_provisioned = int((result or {}).get("cost_codes_provisioned") or 0)

        def _persist() -> Project:
            with SessionLocal() as session:
                project = project_repository.adopt_gp_job(
                    session, job_number=job_number, job_name=job_name, company=company
                )
                session.commit()
                session.refresh(project)
                return project_to_type(project)

        try:
            # Off the event loop: the /relay-link read loop runs on it and must not block on Postgres.
            return CreateGpJobResult(
                project=await asyncio.to_thread(_persist),
                created=True,
                cost_codes_provisioned=cost_codes_provisioned,
            )
        except ConflictError:
            # The sync adopted this job between GP committing and us persisting. Benign race, same as
            # the one _persist_missing swallows from the other side - the row we wanted exists.
            # GP still created the job on this call, so this is a real creation - only the Nexus row
            # was written by someone else first.
            logger.info("create_gp_job: %s was adopted by the sync first", job_number)
            return CreateGpJobResult(
                project=await asyncio.to_thread(_load_project, job_number, company),
                created=True,
                cost_codes_provisioned=cost_codes_provisioned,
            )
        except Exception:
            # The job EXISTS in GP at this point - that call already committed. Losing the Nexus row is
            # recoverable rather than fatal: the sync adopts it on its next pass, and retrying the
            # dialog now lands on the job_already_exists path above. Still an error to the caller,
            # because the project is not there yet when the dialog closes.
            logger.exception("create_gp_job: GP created %s but the project persist failed", job_number)
            raise

    @strawberry.mutation
    async def sync_gp_jobs(self, info: strawberry.Info) -> GpJobSyncResult:
        """Run one pass of the GP job sync now, instead of waiting out the poll interval.

        The background service already does this on a timer and on every relay reconnect, so this is
        for the case where someone wants to see the result immediately - after creating a job directly
        in GP, or when checking whether the sync is working at all."""
        total, adopted = await gp_job_sync.run_once()
        return GpJobSyncResult(total=total, adopted=adopted)

    @strawberry.mutation
    async def update_project(self, info: strawberry.Info, id: strawberry.ID, input: UpdateProjectInput) -> Project:
        """Edit a project with one Save: GP's half into GP first, then Nexus's half (#730).

        If GP contains it, GP owns it. When any GP-held field changed, the changed ones are written
        into GP through the relay's update_job, GP's record of the job as it now stands is read back
        and applied (GP-PROCESSING for a job edit), and only then are the Nexus-only fields saved, all
        in one commit. A relay that is unreachable, too slow, too old, or a GP refusal raises and saves
        NOTHING - not even the Nexus-only half - and queues nothing: the dialog is still open, so the
        person retries it, and a Nexus-side save of a GP field GP never took would be overwritten by
        the next GP JOBS SYNC anyway.

        When no GP-held field changed the relay is not involved at all, so editing a project manager
        or a GC phone number works with the relay down.

        This replaces #497's save-then-push, which committed the edit in Nexus and replicated the name
        and address to GP afterwards, queueing it when the relay was away. Any of those pushes still
        queued drain as before; nothing new is queued."""
        pid = uuid.UUID(str(id))
        scope = await asyncio.to_thread(tenant_scope, info)
        changes, job_number, company = await asyncio.to_thread(_plan_project_edit, pid, scope, input)

        record = None
        if changes:
            relay_gateway.require_feature(JOB_MIRROR_FEATURE, "update_job")
            try:
                result = await relay_gateway.relay_call(company, "update_job", {"job_number": job_number, **changes})
            except RelayCallError as e:
                refusal = project_repository.gp_job_refusal(e, job_number)
                if refusal is not None:
                    raise refusal from e
                # GP's own words for any other refusal, with its error body kept for the dialog.
                raise validation_error_from_relay(e) from e
            record = (result or {}).get("job")
            if not isinstance(record, dict):
                # GP took the edit but the reply carried no job to read back. The next GP JOBS SYNC
                # brings the project level; refusing now would tell the person GP did not take it.
                logger.warning("update_project: GP updated job %s but returned no job record", job_number)
                record = None

        return await asyncio.to_thread(_save_project_edit, pid, input, record)

    @strawberry.mutation
    def set_project_archived(self, info: strawberry.Info, id: strawberry.ID, archived: bool) -> Project:
        """Hide a project from the picker every module reads, or bring it back (#637).

        A tenant owner's decision, and deliberately the whole of what archiving does: nothing about
        the project's POs, inventory, pull requests or shipments changes. It is a decision about what
        people can START new work against, not a lifecycle state.

        Scoped by id (#729), for the same reason `adminProjectDetail` beside it now is: a TENANT
        OWNER is pinned to their company, so another company's project is not theirs to archive."""
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            project = project_repository.set_project_archived(session, uuid.UUID(str(id)), archived)
            session.commit()
            session.refresh(project)
            return project_to_type(project, include_openings=False)


# The GP-held text fields a job edit may change (#730): the input attribute, which is also the project
# column, and the key update_job takes it under.
_GP_TEXT_EDITS = (
    ("description", "job_name"),
    ("customer_number", "customer_number"),
    ("job_address_code", "job_address_code"),
    ("billto_address_code", "billto_address_code"),
    ("address", "address1"),
    ("address2", "address2"),
    ("city", "city"),
    ("state", "state"),
    ("zip", "zip_code"),
    ("country", "country"),
    ("division", "division"),
    ("tax_schedule_id", "tax_schedule_id"),
    ("use_tax_schedule_id", "use_tax_schedule_id"),
    ("estimator_id", "estimator_id"),
    ("ws_manager_id", "ws_manager_id"),
)

# The GP-held dates a job edit may change, named the same on the input, the column and the wire.
_GP_DATE_EDITS = ("schedule_start_date", "scheduled_completion_date", "bid_due_date")

# Everything else the edit carries is Nexus's alone and never goes near GP.
_NEXUS_ONLY_EDITS = (
    "job_site_name",
    "contractor",
    "project_manager",
    "application",
    "gc_contact_name",
    "gc_phone",
    "gc_email",
    "off_site_storage_agreement",
)


def _gp_job_changes(project, input: UpdateProjectInput) -> dict:
    """The GP-held fields this edit actually changes, as update_job's payload keys (job number not
    included). Empty when the edit touches nothing GP holds.

    Only what changed is sent, so an unchanged field can never overwrite something GP holds that Nexus
    has not caught up with yet. A blank or a cleared date counts as no change: update_job reads a blank
    as "not sent", so GP cannot be told to clear a field this way, and sending one would only look like
    it had been. The relay's other rules are applied here so they refuse before GP is asked: the street
    and the city travel together; a new site address mints its own job address code, so it never goes
    with a picked one; and a new customer takes its bill-to address code and a site with it."""
    changes: dict = {}
    for attr, key in _GP_TEXT_EDITS:
        value = (getattr(input, attr) or "").strip()
        if value and value != (getattr(project, attr) or "").strip():
            changes[key] = value
    for name in _GP_DATE_EDITS:
        value = getattr(input, name)
        if value is not None and value != getattr(project, name):
            changes[name] = value.isoformat()

    if "address1" in changes or "city" in changes:
        changes.setdefault("address1", (project.address or "").strip())
        changes.setdefault("city", (project.city or "").strip())
        if not changes["address1"] or not changes["city"]:
            raise ValidationError("A site address needs both a street and a city", field="address")
        if "job_address_code" in changes:
            raise ValidationError(
                "Pick a job address code or enter a new site address, not both - a new site address "
                "becomes the job's address code in GP",
                field="job_address_code",
            )

    if "customer_number" in changes:
        billto = (input.billto_address_code or "").strip()
        if not billto:
            raise ValidationError(
                "A new customer needs one of its own bill-to address codes", field="billto_address_code"
            )
        changes["billto_address_code"] = billto
        if "address1" not in changes:
            job_address = (input.job_address_code or "").strip()
            if not job_address:
                raise ValidationError(
                    "A new customer needs one of its own job address codes, or a new site address",
                    field="job_address_code",
                )
            changes["job_address_code"] = job_address
    return changes


def _plan_project_edit(pid: uuid.UUID, scope: str | None, input: UpdateProjectInput) -> tuple[dict, str, str]:
    """Read-only first half of a project edit: (GP changes, job number, company). Everything that can
    refuse the edit before GP is asked refuses here - out of scope, a changed client, or a GP change
    against a job GP will not take one on."""
    with SessionLocal() as session:
        tenancy.require_project_in_scope(session, pid, scope)
        project = project_repository.get_project(session, pid)
        if project is None:
            raise NotFoundError(f"Project {pid} not found")
        if input.client is not None and input.client.strip() != (project.client or "").strip():
            raise ValidationError(
                "The client is the GP customer's name, which GP holds. Change the customer instead.",
                field="client",
            )
        changes = _gp_job_changes(project, input)
        if changes:
            project_repository.require_gp_job_open(session, pid)
        return changes, project.project_id, project.company


def _save_project_edit(pid: uuid.UUID, input: UpdateProjectInput, record: dict | None) -> Project:
    """Second half: GP's read-back onto the GP-held fields, then the Nexus-only fields, in one commit."""
    with SessionLocal() as session:
        project = project_repository.get_project(session, pid)
        if project is None:
            raise NotFoundError(f"Project {pid} not found")
        if record is not None:
            project_repository.apply_gp_job_record(project, record)
        project = project_repository.update_project(
            session, pid, **{name: getattr(input, name) for name in _NEXUS_ONLY_EDITS}
        )
        session.commit()
        session.refresh(project)
        return project_to_type(project)
