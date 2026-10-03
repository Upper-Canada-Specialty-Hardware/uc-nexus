"""Organising staged hardware into the things that physically go on the truck (#451).

The staging pool is everything a completed shipping pull has put on the floor: assembled leaves at
SHIP_READY, and loose quantities that were picked but not yet shipped. Containers are how that pool
gets arranged - a skid stacked in unload order, a box of loose parts, an envelope of keys - built up
over hours or days and then confirmed as one shipment.

Three ceilings, and they are all about physical objects rather than policy:

  - a skid holds at most `MAX_LEAVES_PER_SKID` leaves, because a taller stack cannot be strapped
  - one assembled leaf sits in at most one open container, because there is one of it
  - loose placements cannot exceed what is actually staged and unplaced

Nothing here moves inventory. The hardware left when its pull was picked (#367).
"""

import uuid

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError, ValidationError
from app.models.enums import ShipmentContainerType
from app.models.project import Project
from app.models.shipment_container import (
    ShipmentContainer,
    ShipmentContainerItem,
)

# The two container types loaded in a sequence somebody reverses at the far end, and therefore the
# only two whose `position` is worth showing.
STACKED_TYPES = (ShipmentContainerType.SKID, ShipmentContainerType.DOOR_CART)


def loose_key(opening_number: str | None, hardware_category: str, product_code: str) -> tuple[str | None, str, str]:
    """How a staged loose quantity is identified, everywhere on this path.

    The opening is part of it because `get_ship_ready_items` groups the staged pool that way and
    `confirm_shipment` checks availability that way. Keying containers on the product alone reads as
    harmless right up until two openings stage the same product: the pool would report one of the two
    quantities as if it were the total, and a placement the staging rules accepted would be refused
    at confirm - or booked against an opening it was never pulled for.

    Null is a real value here, not a missing one. A pull raised straight off inventory has no opening
    to attribute (#451), and those units are their own bucket rather than everyone's.
    """
    return (opening_number, hardware_category, product_code)


def lock_staging_pool(session: Session, project_id: uuid.UUID) -> None:
    """Serialise every write that is measured against this project's staged pool (#1107).

    The pool is not a row. It is arithmetic over completed pulls, packing slips and open containers,
    so there is nothing of its own to lock - and checking it unlocked let two people confirming the
    same containers both pass, minting two slips for one load. The project row stands in for it:
    every confirm and every container save takes this lock before reading the pool, so the second
    one reads it after the first has committed.

    FOR NO KEY UPDATE rather than FOR UPDATE. The plain form also conflicts with the key-share lock
    that every insert of a row referencing the project takes, which would stall unrelated writes on
    the job (a receive, a request) for the length of a confirm.
    """
    session.execute(select(Project.id).where(Project.id == project_id).with_for_update(key_share=True))


def get_containers(session: Session, project_id: uuid.UUID, *, open_only: bool = True) -> list[ShipmentContainer]:
    """Containers for one project, items eagerly loaded (the type builder walks them).

    `open_only` is what the staging workspace asks for: a shipped container is on its slip and is
    not something anyone can still load.
    """
    stmt = (
        select(ShipmentContainer)
        .options(selectinload(ShipmentContainer.items))
        .where(ShipmentContainer.project_id == project_id)
        .order_by(ShipmentContainer.created_at.asc())
    )
    if open_only:
        stmt = stmt.where(ShipmentContainer.packing_slip_id.is_(None))
    return list(session.scalars(stmt).unique().all())


# The column is String(100) (#1175). Longer failed at flush and reached the user as a masked
# "unexpected error" rather than a message about the name.
NAME_MAX = 100


def _clean_name(name: str | None) -> str:
    name = (name or "").strip()
    if not name:
        raise ValidationError("A container needs a name - the label that goes on it.", field="name")
    if len(name) > NAME_MAX:
        raise ValidationError(f"A container name can be at most {NAME_MAX} characters.", field="name")
    return name


def create_container(
    session: Session,
    project_id: uuid.UUID,
    *,
    container_type: ShipmentContainerType,
    name: str,
    created_by: str,
) -> ShipmentContainer:
    name = _clean_name(name)
    _check_name_free(session, project_id, name)
    container = ShipmentContainer(
        id=uuid.uuid4(),
        project_id=project_id,
        container_type=container_type,
        name=name,
        created_by=created_by,
    )
    session.add(container)
    session.flush()
    return container


def rename_container(session: Session, container_id: uuid.UUID, name: str) -> ShipmentContainer:
    container = _open_container(session, container_id)
    name = _clean_name(name)
    if name != container.name:
        _check_name_free(session, container.project_id, name)
        container.name = name
    session.flush()
    return container


def delete_container(session: Session, container_id: uuid.UUID) -> None:
    """Break a container back down. Its contents return to the unplaced pool.

    Open only. A shipped container is part of a slip's record of what went on the truck, and there
    is nothing to undo about it here - that is what a return is for.
    """
    container = _open_container(session, container_id)
    session.delete(container)
    session.flush()


def set_container_items(
    session: Session,
    container_id: uuid.UUID,
    items: list[dict],
) -> ShipmentContainer:
    """Rewrite a container's contents to exactly `items`, in the order given.

    One batch call rather than place / remove / reorder as three, because a drag-and-drop surface
    already holds the whole list and saving it in pieces means a moment where the stack is in an
    order nobody chose. `position` is assigned from the list index, so the caller never computes it.

    The staged pool is read here, inside the same transaction as the write, rather than taken from
    the caller: what is free to place has to be measured against the other containers as they are at
    the moment of saving, not as they were when the screen was drawn.
    """
    project_id = session.scalar(select(ShipmentContainer.project_id).where(ShipmentContainer.id == container_id))
    if project_id is None:
        raise NotFoundError(f"Shipment container {container_id} not found")
    # Pool first, then the container: the same order the confirm takes them in (#1107). Two saves
    # into different containers each counted the other's placements as they were before either
    # committed, and between them could place more than was staged.
    lock_staging_pool(session, project_id)
    container = _open_container(session, container_id)
    staged_pool = build_staged_pool(session, container.project_id)

    # A manual line is free-text hardware that was never in Nexus inventory, so it is not measured
    # against the staged pool - only validated as a well-formed line. Real lines are aggregated and
    # checked against what is genuinely staged and unplaced.
    wanted: dict[tuple[str | None, str, str], int] = {}
    for item in items:
        category = (item.get("hardware_category") or "").strip()
        product = (item.get("product_code") or "").strip()
        quantity = int(item.get("quantity", 1))
        # Every line, not only manual ones (#1107). A negative real line paired with a matching
        # positive one passed the aggregate check and wrote a negative row, which the confirm then
        # carried onto the slip - growing the staged pool by hardware that does not exist.
        if quantity < 1:
            raise ValidationError("Every line needs a quantity of at least 1.", field="items")
        if item.get("is_manual"):
            if not category or not product:
                raise ValidationError(
                    "A manual line needs a hardware category and a product code.",
                    field="items",
                )
            continue
        key = loose_key(item.get("opening_number"), item["hardware_category"], item["product_code"])
        wanted[key] = wanted.get(key, 0) + quantity

    _check_available(session, container, wanted, staged_pool)

    for existing in list(container.items):
        session.delete(existing)
    session.flush()

    for index, item in enumerate(items):
        session.add(
            ShipmentContainerItem(
                id=uuid.uuid4(),
                shipment_container_id=container.id,
                opening_number=item.get("opening_number"),
                hardware_category=item["hardware_category"],
                product_code=item["product_code"],
                quantity=int(item.get("quantity", 1)),
                is_manual=bool(item.get("is_manual", False)),
                # The list order IS the stacking order. Index 0 is loaded first, which on a skid is
                # the bottom of the stack.
                position=index,
            )
        )
    session.flush()
    # The rows were written by id rather than appended, so the loaded collection is stale - the same
    # trap the shipping-request edit hit (#451).
    session.expire(container, ["items"])
    return container


def move_between_containers(
    session: Session,
    source_id: uuid.UUID,
    source_items: list[dict],
    target_id: uuid.UUID,
    target_items: list[dict],
) -> tuple[ShipmentContainer, ShipmentContainer]:
    """Rewrite two containers of one project in one transaction: a move from one to the other (#1178).

    The screen used to make the move as two saves. A refused target save left the item in neither
    container, back in the unplaced pool. Here the source is written first and flushed, so the target
    is gated against stock the source no longer holds, and a refusal anywhere rolls both back.
    """
    if source_id == target_id:
        raise ValidationError("A move needs two different containers.", field="target")
    projects = set(
        session.scalars(
            select(ShipmentContainer.project_id).where(ShipmentContainer.id.in_([source_id, target_id]))
        ).all()
    )
    if len(projects) != 1:
        raise ValidationError("Both containers must belong to the same project.", field="target")
    source = set_container_items(session, source_id, source_items)
    target = set_container_items(session, target_id, target_items)
    return source, target


def confirm_shipment_from_containers(
    session: Session,
    project_id: uuid.UUID,
    container_ids: list[uuid.UUID],
    *,
    shipped_by: str,
    details: dict | None,
):
    """Ship the named containers as one shipment (#451).

    Deliberately a thin wrapper over `confirm_shipment` rather than a second confirm path: that
    function owns the quarantine gate, the slip-number mint, the uniqueness backstop and the
    availability arithmetic, and a container flow that re-implemented any of them would be a second
    set of rules to keep in step.

    All this adds is where the items come from - including their manual flag - and, afterwards,
    stamping the slip onto the containers so they read as shipped instead of staying open and
    re-shippable.
    """
    from app.repositories import shipping_repository

    if not container_ids:
        raise ValidationError("Pick at least one container to ship.", field="containerIds")

    # #1107: the pool lock before anything is read, then the containers in id order. A second confirm
    # of the same containers waits here, and once it gets through `_open_container` sees the first
    # one's slip on them and refuses - rather than minting a second slip and moving the containers
    # onto it.
    lock_staging_pool(session, project_id)

    # Deduplicated before loading. The same id twice builds the item list twice, which doubles every
    # loose quantity on the slip and makes `confirm_shipment`'s leaf count disagree with the number
    # of distinct leaves it found - reported as the leaf not existing. Sorted so two confirms lock
    # overlapping sets in the same order.
    containers = [_open_container(session, cid) for cid in sorted(dict.fromkeys(container_ids))]
    for container in containers:
        if container.project_id != project_id:
            raise ValidationError(f"{container.name} belongs to another project.", field="containerIds")
        if not container.items:
            raise ValidationError(
                f"{container.name} is empty. Put something in it or leave it behind.",
                field="containerIds",
            )

    items = [
        {
            "opening_number": item.opening_number,
            "product_code": item.product_code,
            "hardware_category": item.hardware_category,
            "quantity": item.quantity,
            "is_manual": item.is_manual,
        }
        for container in containers
        for item in sorted(container.items, key=lambda i: i.position)
    ]

    slip = shipping_repository.confirm_shipment(
        session,
        project_id,
        shipped_by,
        items,
        details,
    )
    for container in containers:
        container.packing_slip_id = slip.id
    session.flush()
    return slip


def build_staged_pool(
    session: Session,
    project_id: uuid.UUID,
    *,
    ready: dict | None = None,
    containers: list[ShipmentContainer] | None = None,
) -> dict:
    """What this project has staged, and how much of it is already in an open container.

    `{(opening, category, product): {"staged": n, "placed": n}}`

    The staged side comes from `get_ship_ready_items`, which is the existing definition of what is
    out of inventory and not yet shipped; this only adds where it has been put since.

    `ready` and `containers` are accepted so a caller that has already read them - the workspace
    query renders all three - can hand them over instead of paying for the same two reads twice.
    `get_ship_ready_items` alone is three statements plus a selectinload.
    """
    from app.repositories import shipping_repository

    if ready is None:
        ready = shipping_repository.get_ship_ready_items(session, project_id)
    if containers is None:
        containers = get_containers(session, project_id, open_only=True)

    pool: dict = {}
    for li in ready["loose_items"]:
        # Summed, not assigned. Two openings staging the same product are two rows here, and the last
        # one winning would publish one opening's quantity as if it were the whole floor.
        key = loose_key(li["opening_number"], li["hardware_category"], li["product_code"])
        bucket = pool.setdefault(key, {"staged": 0, "placed": 0})
        bucket["staged"] += li["available_quantity"]

    for container in containers:
        for item in container.items:
            # A manual line was never part of the staged pool, so it does not consume it. Counting it
            # as placed would let a manual line matching a real staged combo eat pool a genuine drag
            # is entitled to.
            if item.is_manual:
                continue
            key = loose_key(item.opening_number, item.hardware_category, item.product_code)
            bucket = pool.setdefault(key, {"staged": 0, "placed": 0})
            bucket["placed"] += item.quantity
    return pool


def _check_available(
    session: Session,
    container: ShipmentContainer,
    wanted: dict[tuple[str | None, str, str], int],
    staged_pool: dict,
) -> None:
    """Placements cannot exceed what is staged, counting what OTHER open containers hold.

    This container's own current contents are added back before comparing, so re-saving a container
    unchanged - or trimming it - is never refused for the units it is already holding.
    """
    held_here: dict[tuple[str | None, str, str], int] = {}
    for item in container.items:
        # #1301: a manual line is not counted as placed in `build_staged_pool`, so adding it back here
        # would hand a real line keyed the same as it free units that were never staged.
        if item.is_manual:
            continue
        key = loose_key(item.opening_number, item.hardware_category, item.product_code)
        held_here[key] = held_here.get(key, 0) + item.quantity

    for key, quantity in sorted(wanted.items(), key=lambda pair: tuple(str(part) for part in pair[0])):
        opening_number, category, product = key
        bucket = staged_pool.get(key, {"staged": 0, "placed": 0})
        free = bucket["staged"] - bucket["placed"] + held_here.get(key, 0)
        if quantity > free:
            owed_to = f" for opening {opening_number}" if opening_number else ""
            raise ValidationError(
                f"{category} {product}{owed_to}: {quantity} placed but only {max(0, free)} staged and "
                "unplaced. Ship what is staged, or pull more first.",
                field="items",
            )


def _open_container(session: Session, container_id: uuid.UUID) -> ShipmentContainer:
    """The container, row-locked and re-read, and refused if it has already shipped.

    Locked because every caller goes on to change it or ship it (#1107), and the shipped check is
    only worth anything against a row nobody else is mid-confirm on. `populate_existing` because an
    earlier read in the same session would otherwise hand back the copy from before the lock.
    """
    container = (
        session.scalars(
            select(ShipmentContainer)
            .options(selectinload(ShipmentContainer.items))
            .where(ShipmentContainer.id == container_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        .unique()
        .first()
    )
    if container is None:
        raise NotFoundError(f"Shipment container {container_id} not found")
    if container.packing_slip_id is not None:
        raise InvalidStateTransitionError(
            f"{container.name} has already shipped. A shipped container is part of that shipment's "
            "record and cannot be changed."
        )
    return container


def _check_name_free(session: Session, project_id: uuid.UUID, name: str) -> None:
    """One open container per name per project, so "Skid 1" cannot be built twice at once."""
    existing = session.scalars(
        select(ShipmentContainer).where(
            ShipmentContainer.project_id == project_id,
            ShipmentContainer.packing_slip_id.is_(None),
            ShipmentContainer.name == name,
        )
    ).first()
    if existing is not None:
        raise ConflictError(f"An open container named {name} already exists on this project", field="name")
