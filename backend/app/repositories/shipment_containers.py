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
from app.models.enums import PullRequestItemType, ShipmentContainerType
from app.models.shipment_container import (
    MAX_LEAVES_PER_SKID,
    ShipmentContainer,
    ShipmentContainerItem,
)

# The two container types loaded in a sequence somebody reverses at the far end, and therefore the
# only two whose `position` is worth showing.
STACKED_TYPES = (ShipmentContainerType.SKID, ShipmentContainerType.DOOR_CART)


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


def create_container(
    session: Session,
    project_id: uuid.UUID,
    *,
    container_type: ShipmentContainerType,
    name: str,
    created_by: str,
) -> ShipmentContainer:
    name = (name or "").strip()
    if not name:
        raise ValidationError("A container needs a name - the label that goes on it.", field="name")
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
    name = (name or "").strip()
    if not name:
        raise ValidationError("A container needs a name - the label that goes on it.", field="name")
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
    container = _open_container(session, container_id)
    staged_pool = build_staged_pool(session, container.project_id)

    leaf_ids: set[uuid.UUID] = set()
    loose_wanted: dict[tuple[str, str], int] = {}
    for item in items:
        item_type = PullRequestItemType(item["item_type"])
        if item_type == PullRequestItemType.OPENING_ITEM:
            oi_id = item.get("opening_item_id")
            if not oi_id:
                raise ValidationError(
                    "An assembled-leaf placement must name its opening item.", field="opening_item_id"
                )
            oi_id = uuid.UUID(str(oi_id))
            if oi_id in leaf_ids:
                raise ValidationError("The same door leaf cannot be placed twice in one container.", field="items")
            leaf_ids.add(oi_id)
        else:
            key = (item["hardware_category"], item["product_code"])
            loose_wanted[key] = loose_wanted.get(key, 0) + int(item.get("quantity", 1))

    if container.container_type is ShipmentContainerType.SKID and len(leaf_ids) > MAX_LEAVES_PER_SKID:
        raise ValidationError(
            f"A skid holds at most {MAX_LEAVES_PER_SKID} door leaves; this one would carry {len(leaf_ids)}. "
            "Start another skid.",
            field="items",
        )

    _check_leaves_available(session, container, leaf_ids, staged_pool)
    _check_loose_available(session, container, loose_wanted, staged_pool)

    for existing in list(container.items):
        session.delete(existing)
    session.flush()

    for index, item in enumerate(items):
        item_type = PullRequestItemType(item["item_type"])
        session.add(
            ShipmentContainerItem(
                id=uuid.uuid4(),
                shipment_container_id=container.id,
                item_type=item_type,
                opening_item_id=(uuid.UUID(str(item["opening_item_id"])) if item.get("opening_item_id") else None),
                opening_number=item.get("opening_number"),
                leaf=item.get("leaf"),
                hardware_category=item["hardware_category"],
                product_code=item["product_code"],
                quantity=int(item.get("quantity", 1)),
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


def confirm_shipment_from_containers(
    session: Session,
    project_id: uuid.UUID,
    container_ids: list[uuid.UUID],
    *,
    packing_slip_number: str,
    shipped_by: str,
    details: dict | None,
):
    """Ship the named containers as one shipment (#451).

    Deliberately a thin wrapper over `confirm_shipment` rather than a second confirm path: that
    function owns the quarantine gate, the slip-number uniqueness check, the SHIP_READY transition
    and the loose-availability arithmetic, and a container flow that re-implemented any of them
    would be a second set of rules to keep in step.

    All this adds is where the items come from and, afterwards, stamping the slip onto the
    containers so they read as shipped instead of staying open and re-shippable.
    """
    from app.repositories import shipping_repository

    if not container_ids:
        raise ValidationError("Pick at least one container to ship.", field="containerIds")

    containers = [_open_container(session, cid) for cid in container_ids]
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
            "item_type": item.item_type,
            "opening_item_id": item.opening_item_id,
            "opening_number": item.opening_number,
            "product_code": item.product_code,
            "hardware_category": item.hardware_category,
            "quantity": item.quantity,
        }
        for container in containers
        for item in sorted(container.items, key=lambda i: i.position)
    ]

    slip = shipping_repository.confirm_shipment(
        session,
        project_id,
        packing_slip_number,
        shipped_by,
        items,
        details,
    )
    for container in containers:
        container.packing_slip_id = slip.id
    session.flush()
    return slip


def build_staged_pool(session: Session, project_id: uuid.UUID) -> dict:
    """What this project has staged, and how much of it is already in an open container.

    `{"leaves": {opening_item_id: placed_in_container_id | None},
      "loose": {(category, product): {"staged": n, "placed": n}}}`

    The staged side comes from `get_ship_ready_items`, which is the existing definition of what is
    out of inventory and not yet shipped; this only adds where it has been put since.
    """
    from app.repositories import shipping_repository

    ready = shipping_repository.get_ship_ready_items(session, project_id)
    pool = {
        "leaves": {oi.id: None for oi in ready["opening_items"]},
        "loose": {
            (li["hardware_category"], li["product_code"]): {"staged": li["available_quantity"], "placed": 0}
            for li in ready["loose_items"]
        },
    }

    for container in get_containers(session, project_id, open_only=True):
        for item in container.items:
            if item.item_type == PullRequestItemType.OPENING_ITEM and item.opening_item_id is not None:
                # Only stamp a leaf the pool already knows about. A container can outlive its
                # contents' staged state - the cart on the Ship tab can still ship a leaf out from
                # under a skid while both paths exist - and inventing a key here would make that
                # phantom look like a legitimately placed leaf and let it be placed again.
                if item.opening_item_id in pool["leaves"]:
                    pool["leaves"][item.opening_item_id] = container.id
            elif item.item_type == PullRequestItemType.LOOSE:
                key = (item.hardware_category, item.product_code)
                bucket = pool["loose"].setdefault(key, {"staged": 0, "placed": 0})
                bucket["placed"] += item.quantity
    return pool


def _check_leaves_available(
    session: Session,
    container: ShipmentContainer,
    leaf_ids: set[uuid.UUID],
    staged_pool: dict,
) -> None:
    """Every leaf named must be staged, and must not already sit in a different open container."""
    leaves = staged_pool["leaves"]
    for oi_id in sorted(leaf_ids, key=str):
        if oi_id not in leaves:
            raise ValidationError(
                "That door leaf is not staged for shipping - only leaves whose pull has completed can be loaded.",
                field="opening_item_id",
            )
        holder = leaves[oi_id]
        if holder is not None and holder != container.id:
            other = session.get(ShipmentContainer, holder)
            raise ConflictError(
                f"That door leaf is already in {other.name if other else 'another container'}. "
                "Take it out of there first - there is only one of it.",
                field="opening_item_id",
            )


def _check_loose_available(
    session: Session,
    container: ShipmentContainer,
    wanted: dict[tuple[str, str], int],
    staged_pool: dict,
) -> None:
    """Loose placements cannot exceed what is staged, counting what OTHER open containers hold.

    This container's own current contents are added back before comparing, so re-saving a container
    unchanged - or trimming it - is never refused for the units it is already holding.
    """
    held_here: dict[tuple[str, str], int] = {}
    for item in container.items:
        if item.item_type == PullRequestItemType.LOOSE:
            key = (item.hardware_category, item.product_code)
            held_here[key] = held_here.get(key, 0) + item.quantity

    for key, quantity in sorted(wanted.items()):
        bucket = staged_pool["loose"].get(key, {"staged": 0, "placed": 0})
        free = bucket["staged"] - bucket["placed"] + held_here.get(key, 0)
        if quantity > free:
            raise ValidationError(
                f"{key[0]} {key[1]}: {quantity} placed but only {max(0, free)} staged and unplaced. "
                "Ship what is staged, or pull more first.",
                field="items",
            )


def _open_container(session: Session, container_id: uuid.UUID) -> ShipmentContainer:
    container = (
        session.scalars(
            select(ShipmentContainer)
            .options(selectinload(ShipmentContainer.items))
            .where(ShipmentContainer.id == container_id)
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
