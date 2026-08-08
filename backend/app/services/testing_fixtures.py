"""Fixtures that put the database into a state the UI cannot reach by hand (#470).

Only one so far, and it exists because of a ceiling nobody could ever see enforced. A skid holds
thirty door leaves; reaching that through the app means thirty openings taken through purchase,
receipt, a shop assembly pull, a pick, assembly, a shipping pull and a second pick. Nobody was ever
going to do that, so the `n/30` chip, the greyed-out Place-in entry and the warning toast shipped
having only been read, never run.

Nothing here is reachable off a test target: every caller sits behind `require_testing_request`,
the same double gate as `/testing/clerk-sign-in` (#422). Read that as load-bearing rather than
belt-and-braces - this module writes rows that the rest of the system treats as physical objects
sitting in a warehouse, and a leaf minted here never went through assembly, so on anything holding
real data it is an invented door.
"""

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.errors import NotFoundError, ValidationError
from app.models.enums import OpeningItemState
from app.models.opening_item import OpeningItem, OpeningItemHardware
from app.models.project import Project
from app.repositories import warehouse_admin_repository

# Enough to fill a skid and be refused the next one, with room to spare. Capped rather than open:
# the count arrives on a query string, and a fixture that mints a hundred thousand leaves off a
# typo is a slow way to lose an environment.
MAX_SEEDED_LEAVES = 200


def seed_ship_ready_leaves(
    session: Session,
    project_id: uuid.UUID,
    count: int,
    *,
    opening_prefix: str = "FIXT",
) -> dict:
    """Mint `count` assembled door leaves at SHIP_READY for one project, skipping the pull cycle.

    Each leaf gets its own opening number and its own `opening_id`, so `uq_opening_items_live_leaf`
    (one live assembled unit per project/opening/leaf) is satisfied by construction and a second call
    on the same project adds to the pool rather than colliding with it.

    They land in the staging pool immediately: `get_ship_ready_items` selects on state alone, and
    `build_staged_pool` puts every one it returns on the floor as unplaced. Loose hardware is NOT
    seeded - that side comes from completed shipping pulls, and the leaf paths are what this is for.

    One `OpeningItemHardware` row each, so the leaf reads as an assembled unit anywhere the installed
    hardware is shown rather than as an empty shell. It is inert to the pool arithmetic: the loose
    quantities come from pull requests and packing slips, never from what was installed.
    """
    if count < 1 or count > MAX_SEEDED_LEAVES:
        raise ValidationError(
            f"Seed between 1 and {MAX_SEEDED_LEAVES} leaves; asked for {count}.",
            field="count",
        )

    project = session.get(Project, project_id)
    if project is None:
        raise NotFoundError(f"Project {project_id} not found")

    # The warehouse does not enter the staging pool or the skid ceiling, but the column is NOT NULL
    # against a RESTRICT foreign key, so one has to exist. Same default every other row that has to
    # land somewhere takes; it raises a ConflictError on a deployment with no warehouses at all.
    warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)

    # Numbered off what this project already holds, so a second call does not reissue opening numbers
    # the first one used and leave two rows on screen that read identically.
    existing = session.scalars(
        select(OpeningItem.opening_number).where(
            OpeningItem.project_id == project_id,
            OpeningItem.opening_number.like(f"{opening_prefix}-%"),
        )
    ).all()
    start = 1
    for number in existing:
        suffix = number.rsplit("-", 1)[-1]
        if suffix.isdigit():
            start = max(start, int(suffix) + 1)

    now = datetime.utcnow()
    created = []
    for offset in range(count):
        opening_number = f"{opening_prefix}-{start + offset:04d}"
        leaf = OpeningItem(
            id=uuid.uuid4(),
            project_id=project_id,
            opening_id=uuid.uuid4(),
            warehouse_id=warehouse_id,
            opening_number=opening_number,
            building="Fixture",
            floor="1",
            location="Seeded for testing",
            leaf=1,
            quantity=1,
            assembly_completed_at=now,
            state=OpeningItemState.SHIP_READY,
        )
        session.add(leaf)
        session.flush()
        session.add(
            OpeningItemHardware(
                id=uuid.uuid4(),
                opening_item_id=leaf.id,
                product_code="FIXT-HINGE",
                hardware_category="HINGE",
                quantity=1,
            )
        )
        created.append({"opening_item_id": str(leaf.id), "opening_number": opening_number, "leaf": 1})

    return {
        "created": len(created),
        "warehouse_id": str(warehouse_id),
        "leaves": created,
    }
