"""Shipment loads: the truck trips packing slips ride on (#1720).

A load is started or joined at confirm, and that is the only way a slip gets onto one. It is named for
the lead project and the ship date, the way the outbound supervisor asked for it - `22713-10152026` -
so a shipment can be named out loud instead of as "Thursday's". A second load the same project leads
on the same day is `22713-10152026-2`. Demo loads carry a `D-` in front: the demo company is a copy of
a real one, project numbers and all, and its loads must not take a real load's number.

A load can be joined while it is still on the dock: at least one of its slips is scheduled and none has
been picked up. A cancelled slip stays on its load as history and neither holds it open nor closes it.
"""

import re
import uuid
from datetime import date

from sqlalchemy import exists, func, select
from sqlalchemy.orm import Session, selectinload

from app.demo import is_demo_company
from app.errors import InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import ShipmentStatus
from app.models.project import Project
from app.models.shipment_load import ShipmentLoad
from app.models.shipping import PackingSlip
from app.services.gp_window import local_today
from app.services.locking import lock_rows
from app.status_labels import REFRESH_HINT

# Key for the transaction-scoped advisory lock load numbers are minted under.
_LOAD_NUMBER_LOCK_KEY = 1_720_001

# Statuses that mean the truck has left with the slip on it.
_GONE = (ShipmentStatus.PICKED_UP, ShipmentStatus.DELIVERED)


def load_number_base(project_number: str, ship_date: date, company: str | None) -> str:
    """The name a load gets before any same-day suffix: project number, then the date as MMDDYYYY."""
    base = f"{project_number.strip()}-{ship_date:%m%d%Y}"
    return f"D-{base}" if is_demo_company(company) else base


def mint_load_number(session: Session, base: str, company: str) -> str:
    """Claim `base`, or the next free `base-N` when a load of `company` has it already.

    Per company, because a project number is only unique within one: UBC and TUBC can both have a job
    22713, and one company's truck must not push the other's onto a `-2`. Serialised on an advisory lock
    held to the end of the transaction, so two confirms starting the same project's load on the same day
    cannot both take the bare number.
    """
    session.execute(select(func.pg_advisory_xact_lock(_LOAD_NUMBER_LOCK_KEY)))
    taken = set(
        session.scalars(
            select(ShipmentLoad.load_number).where(
                ShipmentLoad.company == company,
                (ShipmentLoad.load_number == base) | ShipmentLoad.load_number.like(f"{base}-%"),
            )
        )
    )
    if base not in taken:
        return base
    pattern = re.compile(rf"^{re.escape(base)}-(\d+)$")
    used = [int(m.group(1)) for n in taken if (m := pattern.match(n))]
    return f"{base}-{max(used, default=1) + 1}"


def start_load(session: Session, project: Project, ship_date: date | None, created_by: str) -> ShipmentLoad:
    """A new load led by `project`, named for `ship_date` (today in Toronto when the slip has no pickup
    date yet)."""
    day = ship_date or local_today()
    load = ShipmentLoad(
        id=uuid.uuid4(),
        load_number=mint_load_number(
            session, load_number_base(project.project_id, day, project.company), project.company
        ),
        company=project.company,
        lead_project_id=project.id,
        ship_date=day,
        created_by=created_by,
    )
    session.add(load)
    session.flush()
    return load


def _joinable_clause():
    """A load still on the dock: a scheduled slip on it, and no slip on it that has left."""
    return exists().where(
        PackingSlip.load_id == ShipmentLoad.id, PackingSlip.status == ShipmentStatus.SCHEDULED
    ) & ~exists().where(PackingSlip.load_id == ShipmentLoad.id, PackingSlip.status.in_(_GONE))


def joinable_loads(session: Session, company: str) -> list[ShipmentLoad]:
    """The company's loads a new slip can still join, soonest first, with their slips and projects
    loaded for the picker (what it shows of each slip is its number and project)."""
    stmt = (
        select(ShipmentLoad)
        .where(ShipmentLoad.company == company, _joinable_clause())
        .options(
            selectinload(ShipmentLoad.slips).selectinload(PackingSlip.project),
            selectinload(ShipmentLoad.lead_project),
        )
        .order_by(ShipmentLoad.ship_date, ShipmentLoad.load_number)
    )
    return list(session.scalars(stmt).unique().all())


def join_load(session: Session, load_id: uuid.UUID, project: Project) -> ShipmentLoad:
    """The load `project`'s new slip is joining, locked and checked.

    Locked so a pickup recorded on one of its slips cannot land between the check and the join. Refused
    when the load is another company's (a truck never carries two companies' paperwork) or has left.
    """
    locked = lock_rows(session, ShipmentLoad, [load_id])
    # Another company's load reads as absent, the way tenancy answers everywhere else: naming it would
    # tell the caller another company's project number and ship date.
    if not locked or locked[0].company != project.company:
        raise NotFoundError(f"Load {load_id} not found")
    load = locked[0]
    # The slips too: a pickup locks its slip, not the load, so this is what makes it wait for the join
    # (or the join wait for it) rather than land between the check below and the commit.
    lock_rows(session, PackingSlip, list(session.scalars(select(PackingSlip.id).where(PackingSlip.load_id == load.id))))
    joinable = session.scalar(select(ShipmentLoad.id).where(ShipmentLoad.id == load.id, _joinable_clause()))
    if joinable is None:
        raise InvalidStateTransitionError(
            f"Load {load.load_number} has already left the dock, so nothing more can join it. {REFRESH_HINT}"
        )
    return load


def move_slip_to_load(session: Session, slip: PackingSlip, load_id: uuid.UUID | None, moved_by: str) -> ShipmentLoad:
    """Put a scheduled slip on another load, or on a new one of its own when `load_id` is None (#1723).

    The caller holds the slip locked. Only a scheduled slip moves: once it is picked up it went out on
    the truck it was on. A load the move leaves with no slips at all is deleted - it was only ever that
    slip's name, and a load nobody rides is not a truck. One that still carries a cancelled slip stays,
    as the record of it.
    """
    if slip.status != ShipmentStatus.SCHEDULED:
        raise InvalidStateTransitionError(
            f"Shipment {slip.packing_slip_number} has left the dock, so it stays on its load. {REFRESH_HINT}"
        )
    if load_id is not None and load_id == slip.load_id:
        raise ValidationError("The shipment is already on that load.", field="load_id")
    if load_id is None and slip.load_id is not None:
        others = session.scalar(
            select(func.count(PackingSlip.id)).where(PackingSlip.load_id == slip.load_id, PackingSlip.id != slip.id)
        )
        if not others:
            # A new load would only be this one under a new number - and a number already given to the
            # dock and the driver must not change under them.
            raise ValidationError("The shipment is already on a load of its own.", field="load_id")
    project = session.get(Project, slip.project_id)
    old_load_id = slip.load_id
    if load_id is None:
        load = start_load(session, project, slip.pickup_date, moved_by)
    else:
        load = join_load(session, load_id, project)
    slip.load_id = load.id
    session.flush()
    if old_load_id is not None:
        left = session.scalar(select(func.count(PackingSlip.id)).where(PackingSlip.load_id == old_load_id))
        if not left:
            old = session.get(ShipmentLoad, old_load_id)
            if old is not None:
                session.delete(old)
                session.flush()
    return load
