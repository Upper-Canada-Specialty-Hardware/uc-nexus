"""Repository for buyer assignments (issue #216): which projects a GP buyer may create POs for.
Enforcement is STRICT - a buyer with no assignment row cannot create project POs at all; stock POs
(no project) are not gated here.

Cost codes are deliberately NOT part of this authorization. They used to be: each buyer carried a
designated subset of codes, and the register-PO dropdown showed only those. GP has no per-job notion
of "the right cost codes" (WS_Inactive is unused in practice - every job carries its full division
template), so the subset was hand-maintained Nexus config that hid valid codes from purchasers and
blocked legitimate registrations. Whatever GP reports active for the job is now selectable."""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import NotFoundError, ValidationError
from app.models.buyer_assignment import BuyerAssignment
from app.models.project import Project


def _clean_buyer_id(buyer_id: str) -> str:
    cleaned = (buyer_id or "").strip()
    if not cleaned:
        raise ValidationError("Buyer id is required", field="buyer_id")
    return cleaned


def list_assignments(session: Session) -> list[BuyerAssignment]:
    stmt = select(BuyerAssignment).options(selectinload(BuyerAssignment.projects)).order_by(BuyerAssignment.buyer_id)
    return list(session.scalars(stmt).unique().all())


def get_assignment(session: Session, buyer_id: str) -> BuyerAssignment | None:
    stmt = (
        select(BuyerAssignment)
        .options(selectinload(BuyerAssignment.projects))
        .where(BuyerAssignment.buyer_id == _clean_buyer_id(buyer_id))
    )
    return session.scalars(stmt).unique().first()


def save_assignment(session: Session, buyer_id: str, project_ids: list[uuid.UUID]) -> BuyerAssignment:
    """Upsert the one assignment row for a buyer (the admin dialog sends the whole state each save)."""
    cleaned_id = _clean_buyer_id(buyer_id)
    projects = []
    for pid in project_ids:
        project = session.get(Project, pid)
        if project is None:
            raise NotFoundError(f"Project {pid} not found")
        projects.append(project)

    assignment = get_assignment(session, cleaned_id)
    if assignment is None:
        assignment = BuyerAssignment(id=uuid.uuid4(), buyer_id=cleaned_id)
        session.add(assignment)
    assignment.projects = projects
    session.flush()
    return assignment


def delete_assignment(session: Session, buyer_id: str) -> None:
    assignment = get_assignment(session, buyer_id)
    if assignment is None:
        raise NotFoundError(f"No assignment for buyer '{buyer_id}'")
    session.delete(assignment)


def validate_buyer_can_order(session: Session, buyer_id: str, project_id: uuid.UUID | None) -> None:
    """Enforce issue #216 for a PROJECT PO push: the buyer must be assigned to the project. A stock PO
    (project_id None) is not gated. The cost code is not checked here - see the module docstring.
    Raises a clean field error the dialog can show."""
    if project_id is None:
        return

    assignment = get_assignment(session, buyer_id)
    if assignment is None:
        raise ValidationError(
            f"Buyer '{buyer_id}' has no project assignments; an Admin must configure them under Admin -> Buyers",
            field="buyer_id",
        )
    if not any(p.id == project_id for p in assignment.projects):
        raise ValidationError(f"Buyer '{buyer_id}' is not assigned to this project", field="project_id")
