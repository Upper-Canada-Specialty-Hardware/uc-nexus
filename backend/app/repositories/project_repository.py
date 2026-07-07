"""Repository for project CRUD operations."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError, NotFoundError
from app.models.project import Project as ProjectModel


def adopt_gp_job(session: Session, job_number: str, job_name: str | None) -> ProjectModel:
    """Adopt a live GP job (JC00102) as a project. job_number becomes the project's identity
    (project_id, immutable); job_name is a snapshot of GP's job description at adopt time, not
    synced afterward. Raises ConflictError if this job has already been adopted."""
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
