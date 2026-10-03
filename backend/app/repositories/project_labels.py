"""A project's number and name, by id, for rows that only carry the id (#1196, #1173).

The pages that showed a project beside a pull, an open PO or a receive draft used to look the name up
in the `projects` query, which leaves archived projects out - so an archived job's open work showed a
dash. The server reads the label off the project itself instead, in one query per list.
"""

import uuid
from collections.abc import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project

ProjectLabel = tuple[str, str | None]


def project_labels(session: Session, project_ids: Iterable[uuid.UUID | None]) -> dict[uuid.UUID, ProjectLabel]:
    """(job number, description) for every id given, archived projects included. One query."""
    ids = {pid for pid in project_ids if pid is not None}
    if not ids:
        return {}
    rows = session.execute(select(Project.id, Project.project_id, Project.description).where(Project.id.in_(ids)))
    return {pid: (number, description) for pid, number, description in rows}
