"""Project queries + mutations."""

import asyncio
import logging
import uuid

import strawberry

from app.auth import require_admin
from app.database import SessionLocal
from app.errors import ConflictError, NotFoundError, RelayCallError, RelayUnavailableError, ValidationError
from app.repositories import project_repository
from app.services import gp_job_sync
from app.services.relay_gateway import gateway as relay_gateway

from .converters import project_to_type
from .inputs import CreateGpJobInput, UpdateProjectInput
from .types import CreateGpJobResult, GpJobSyncResult, Project, ProjectShipTo

logger = logging.getLogger(__name__)


def _validation_error_from(e: RelayCallError) -> ValidationError:
    """Turn a relay refusal into a ValidationError that still carries the relay's error body.

    main.py's ErrorHandlerExtension publishes `extensions.relayError` from whatever `.detail` the
    raised error has, and ValidationError has no such field - so converting the error plainly would
    strip the GP proc, the error state and the taErrorCode description on the way to the browser, and
    the dialog's GpErrorAlert would render an empty detail table. That table is the whole point of
    #187: error screenshots are how these get reported."""
    error = ValidationError(str(e.message))
    error.detail = e.detail
    return error


def _load_project(job_number: str) -> Project:
    with SessionLocal() as session:
        project = project_repository.get_project_by_schedule_id(session, job_number)
        if project is None:
            raise NotFoundError(f"Project {job_number} not found")
        return project_to_type(project)


async def _adopt_existing(job_number: str) -> Project:
    """Make sure a job GP already holds has its Nexus project, and return it.

    Runs a full sync pass rather than adopting the one job: the pass reads GP's own job master, so the
    project gets GP's name rather than whatever the caller typed, and it is the same code path that
    would have created this project a few minutes later anyway."""
    await gp_job_sync.run_once()
    return await asyncio.to_thread(_load_project, job_number.strip())


@strawberry.type
class ProjectQueries:
    @strawberry.field
    def projects(self) -> list[Project]:
        with SessionLocal() as session:
            rows = project_repository.list_projects_with_opening_counts(session)
            return [project_to_type(p, include_openings=False, opening_count=count) for p, count in rows]

    @strawberry.field
    def admin_projects(self, info: strawberry.Info) -> list[Project]:
        """Admin/Manager-only project list with all editable fields for the admin Projects page."""
        require_admin(info)
        with SessionLocal() as session:
            rows = project_repository.list_projects_with_opening_counts(session)
            return [project_to_type(p, include_openings=False, opening_count=count) for p, count in rows]

    @strawberry.field
    def project_by_schedule_id(self, project_id: str) -> Project | None:
        with SessionLocal() as session:
            p = project_repository.get_project_by_schedule_id(session, project_id)
            if p is None:
                return None
            return project_to_type(p)

    @strawberry.field
    def project_ship_to(self, project_id: strawberry.ID) -> ProjectShipTo | None:
        """The job-site address block for a project, by its UUID - the "deliver to site" ship-to option
        on the generated PO document (issue #230). A lean projection, kept off the PO list query."""
        with SessionLocal() as session:
            p = project_repository.get_project(session, uuid.UUID(str(project_id)))
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

        Admin-only. Creating a job writes to the accounting system of record.
        """
        require_admin(info)

        company = relay_gateway.company
        if not company:
            raise RelayUnavailableError(
                "The GP relay is not connected, so this job cannot be created in GP. Start the relay and try again."
            )

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
                project = await _adopt_existing(input.job_number)
                return CreateGpJobResult(project=project, created=False)
            # GP said no - a closed fiscal period, an address code that isn't on the customer, a
            # division without accounts. The proc words those better than we could, so the message is
            # passed through to the dialog rather than replaced with a generic failure.
            raise _validation_error_from(e) from e

        # GP's own record of what it created, read back from JC00102 by the relay - not the input
        # echoed back (see ops.create_job_op).
        job_number = str((result or {}).get("job_number") or input.job_number).strip()
        job_name = str((result or {}).get("job_name") or input.job_name).strip() or None

        def _persist() -> Project:
            with SessionLocal() as session:
                project = project_repository.adopt_gp_job(session, job_number=job_number, job_name=job_name)
                session.commit()
                session.refresh(project)
                return project_to_type(project)

        try:
            # Off the event loop: the /relay-link read loop runs on it and must not block on Postgres.
            return CreateGpJobResult(project=await asyncio.to_thread(_persist), created=True)
        except ConflictError:
            # The sync adopted this job between GP committing and us persisting. Benign race, same as
            # the one _persist_missing swallows from the other side - the row we wanted exists.
            # GP still created the job on this call, so this is a real creation - only the Nexus row
            # was written by someone else first.
            logger.info("create_gp_job: %s was adopted by the sync first", job_number)
            return CreateGpJobResult(project=await asyncio.to_thread(_load_project, job_number), created=True)
        except Exception:
            # The job EXISTS in GP at this point - that call already committed. Losing the Nexus row is
            # recoverable rather than fatal: the sync adopts it on its next pass, and retrying the
            # dialog now lands on the job_already_exists path above. Still an error to the caller,
            # because the project is not there yet when the dialog closes.
            logger.exception("create_gp_job: GP created %s but the project persist failed", job_number)
            raise

    @strawberry.mutation
    async def sync_gp_jobs(self, info: strawberry.Info) -> GpJobSyncResult:
        """Admin: run one pass of the GP job sync now, instead of waiting out the poll interval.

        The background service already does this on a timer and on every relay reconnect, so this is
        for the case where someone wants to see the result immediately - after creating a job directly
        in GP, or when checking whether the sync is working at all."""
        require_admin(info)
        total, adopted = await gp_job_sync.run_once()
        return GpJobSyncResult(total=total, adopted=adopted)

    @strawberry.mutation
    def update_project(self, info: strawberry.Info, id: strawberry.ID, input: UpdateProjectInput) -> Project:
        require_admin(info)
        with SessionLocal() as session:
            project = project_repository.update_project(
                session,
                uuid.UUID(str(id)),
                description=input.description,
                client=input.client,
                job_site_name=input.job_site_name,
                address=input.address,
                city=input.city,
                state=input.state,
                zip=input.zip,
                contractor=input.contractor,
                project_manager=input.project_manager,
                application=input.application,
                gc_contact_name=input.gc_contact_name,
                gc_phone=input.gc_phone,
                gc_email=input.gc_email,
                off_site_storage_agreement=input.off_site_storage_agreement,
            )
            session.commit()
            session.refresh(project)
            return project_to_type(project)
