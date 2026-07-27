"""Project queries + mutations."""

import asyncio
import uuid

import strawberry

from app.auth import require_admin, require_user
from app.database import SessionLocal
from app.errors import RelayUnavailableError, ValidationError
from app.repositories import project_repository
from app.services.relay_gateway import gateway as relay_gateway

from .converters import project_to_type
from .inputs import AdoptGpJobInput, UpdateProjectInput
from .types import Project, ProjectShipTo


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
    async def adopt_gp_job(self, info: strawberry.Info, input: AdoptGpJobInput) -> Project:
        """Adopt a live GP job as a project (issue #198), verifying it against GP first (#314).

        GP owns jobs: a Nexus project that does not correspond to a real GP job is invalid state, and
        POs, inventory, assembly and shipping all hang off it. This used to trust the caller
        completely - no auth, no `info` parameter at all, and no GP check - so a direct GraphQL call
        could adopt any string, including a fabricated job number, and get a Nexus-only project GP had
        never heard of. The "Adopt GP Job" dialog only ever offered real jobs, but that was UI
        convention, not a guarantee.

        Verification goes through the connected relay's live job master rather than a client-supplied
        company, so the caller cannot choose which GP to be checked against. It uses list_jobs, which
        every shipped relay build already serves, so the guard is live on the installed relay instead
        of waiting on a release (see the op-parity note in #315).

        Refusing when the relay is down is the point, not a limitation: the check is the only thing
        standing between a typo and an orphan project, and "we could not verify" must not mean
        "assume it is fine". The open question of an offline path is recorded on #314.
        """
        require_user(info)
        job_number = (input.job_number or "").strip()
        if not job_number:
            raise ValidationError("job_number is required", field="job_number")

        company = relay_gateway.company
        if not company:
            raise RelayUnavailableError(
                "The GP relay is not connected, so this job cannot be verified against GP. "
                "Start the relay and try again."
            )

        result = await relay_gateway.relay_call(company, "list_jobs")
        jobs = (result or {}).get("jobs") or []
        wanted = job_number.upper()
        match = next((j for j in jobs if str(j.get("job_number") or "").strip().upper() == wanted), None)
        if match is None:
            raise ValidationError(
                f"{job_number} is not a job in GP company {company}. Only an existing GP job can be adopted.",
                field="job_number",
            )

        # GP's own name for the job, not the caller's. The client reads it from the same picker, but
        # it is not the client's to assert - taking GP's keeps the snapshot honest for a direct call.
        job_name = str(match.get("job_name") or "").strip() or input.job_name

        def _persist() -> Project:
            with SessionLocal() as session:
                project = project_repository.adopt_gp_job(
                    session,
                    job_number=job_number,
                    job_name=job_name,
                )
                session.commit()
                session.refresh(project)
                return project_to_type(project)

        # Off the event loop: the /relay-link read loop runs on it and must not block on Postgres.
        return await asyncio.to_thread(_persist)

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
