"""Project queries + mutations."""

import uuid

import strawberry

from app.auth import require_admin
from app.database import SessionLocal
from app.repositories import project_repository

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
    def adopt_gp_job(self, input: AdoptGpJobInput) -> Project:
        """Adopt a live GP job as a project (issue #198). The frontend picks the job from the live
        gpJobs query and posts its number + name here; job_number becomes the project's identity."""
        with SessionLocal() as session:
            project = project_repository.adopt_gp_job(
                session,
                job_number=input.job_number,
                job_name=input.job_name,
            )
            session.commit()
            session.refresh(project)
            return project_to_type(project)

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
