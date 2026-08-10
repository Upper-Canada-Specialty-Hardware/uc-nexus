"""Server-minted pull-request numbers (#493).

Request numbers were typed by hand on the shop-assembly and shipping-out wizard steps. That handed
the user a uniqueness constraint to satisfy from memory: two people raising requests on the same
project at once collided, and nothing tied a number to the job it belonged to.

The number is `<project number>-NNN`, from one counter per project spanning BOTH request types.
They all become warehouse pulls, and a single chronological sequence per project is what a
warehouse user can reason about - two independent sequences would put a 23093-004 on the rack next
to a different 23093-004.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.project import Project as ProjectModel
from app.models.project_request_counter import ProjectRequestCounter


def mint_request_number(session: Session, project_id: uuid.UUID) -> str:
    """Claim the next request number for a project.

    The counter row is locked FOR UPDATE, so two concurrent creates serialize here rather than
    racing to the same number. The lock is held until the caller's transaction commits, which is
    what makes the number and the request it names atomic - a rolled-back create gives the number
    back rather than burning it.
    """
    project = session.get(ProjectModel, project_id)
    if project is None:
        raise ValueError(f"Project {project_id} not found")

    counter = session.scalars(
        select(ProjectRequestCounter).where(ProjectRequestCounter.project_id == project_id).with_for_update()
    ).first()

    if counter is None:
        # A project created after the migration seeded the table. Insert-then-lock rather than
        # lock-then-insert: the primary key makes a concurrent duplicate impossible, and the
        # loser re-reads under the lock below.
        counter = ProjectRequestCounter(project_id=project_id, next_value=1)
        session.add(counter)
        session.flush()

    seq = counter.next_value
    counter.next_value = seq + 1
    session.flush()
    return f"{project.project_id}-{seq:03d}"
