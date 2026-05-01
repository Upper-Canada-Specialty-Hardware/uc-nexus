"""Repository for project CRUD operations."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import ConflictError
from app.models.project import Project as ProjectModel


def create_project(session: Session, project_id: str, description: str, client: str) -> ProjectModel:
    """Create a new project. Raises ConflictError if project_id already exists."""
    existing = session.scalars(select(ProjectModel).where(ProjectModel.project_id == project_id)).first()
    if existing is not None:
        raise ConflictError(
            f"Project number {project_id} already exists",
            field="project_id",
        )

    project = ProjectModel(
        id=uuid.uuid4(),
        project_id=project_id,
        description=description,
        client=client,
    )
    session.add(project)
    session.flush()
    return project
