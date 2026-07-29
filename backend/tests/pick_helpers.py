"""Driving the #367 pick flow from tests that only care that a pull got picked.

`approve_pull_request` used to be one call that both started a pull and deducted its hardware FIFO,
so a test that needed "an approved pull" wrote one line. Picking splits that in two and puts a human
in the middle: `start_pull_request_pick` opens the pull, and `confirm_pick` deducts exactly the rows
somebody dictated.

Most tests do not care which bin the hinges came off - they care that the pull is picked - so
`pick_pull` reproduces the old FIFO behaviour: walk the project's rows for each combo oldest-first
and take what is there. That keeps the sweep of existing tests mechanical, and it means those tests
still assert on the *same* inventory outcome the old approve produced.

Tests that are actually about the pick (which rows, over-pull, short confirms) build their own
`PickLine` lists and call the repository directly - see `test_pick_flow.py`.
"""

import uuid
from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.enums import PullPickLineState, PullRequestItemType, PullRequestStatus
from app.models.inventory import InventoryLocation
from app.models.pull_pick_line import PullPickLine
from app.repositories import warehouse as warehouse_repository


def mark_picked(session: Session, pr, *, by: str = "picker"):
    """Put a pull straight into the state a confirmed pick leaves behind, without picking anything.

    For tests about what happens *after* the pick - the replacement loop, the pipeline ladder - which
    shortcut the warehouse entirely by hand-setting `status`. Before #367 that was enough, because
    completion only checked the status; it now also requires `picked_at`, which is the whole point of
    the gate. Stamping both here keeps those tests shortcutting one concept instead of two, and keeps
    the knowledge of what "worked" means in one place.

    Deliberately not `pick_pull`: these pulls often have no pickable stock behind them (a replacement
    is raised precisely because the shelf was empty), so actually picking them would confirm short and
    leave `picked_at` null - which is the correct behaviour and the wrong fixture.
    """
    pr.status = PullRequestStatus.IN_PROGRESS
    if pr.picked_at is None:
        pr.picked_at = datetime.utcnow()
        pr.picked_by = by
    session.flush()
    return pr


def loose_requirements(pr) -> dict[tuple[str, str], int]:
    """What the pull's LOOSE lines add up to, per combo."""
    required: dict[tuple[str, str], int] = {}
    for item in pr.items:
        if item.item_type != PullRequestItemType.LOOSE:
            continue
        if not item.hardware_category or not item.product_code or item.requested_quantity <= 0:
            continue
        key = (item.hardware_category, item.product_code)
        required[key] = required.get(key, 0) + item.requested_quantity
    return required


def build_pick_lines(session: Session, pr, *, cap: dict[tuple[str, str], int] | None = None):
    """Pick lines that take each combo off the project's oldest rows first - the old FIFO order.

    `cap` limits what is entered per combo, which is how a test asks for a deliberately short
    confirm ("enter 1 of the 4 this pull wants").
    """
    applied = {
        (cat, code): int(total or 0)
        for cat, code, total in session.execute(
            select(
                PullPickLine.hardware_category,
                PullPickLine.product_code,
                func.coalesce(func.sum(PullPickLine.quantity), 0),
            )
            .where(
                PullPickLine.pull_request_id == pr.id,
                PullPickLine.state == PullPickLineState.APPLIED,
            )
            .group_by(PullPickLine.hardware_category, PullPickLine.product_code)
        ).all()
    }

    lines = []
    for (cat, code), total in sorted(loose_requirements(pr).items()):
        remaining = total - applied.get((cat, code), 0)
        if cap is not None:
            remaining = min(remaining, cap.get((cat, code), 0))
        if remaining <= 0:
            continue
        rows = session.scalars(
            select(InventoryLocation)
            .where(
                InventoryLocation.project_id == pr.project_id,
                InventoryLocation.hardware_category == cat,
                InventoryLocation.product_code == code,
            )
            .order_by(InventoryLocation.received_at.asc(), InventoryLocation.id.asc())
        ).all()
        for row in rows:
            if remaining <= 0:
                break
            available = row.quantity - (row.deficient_quantity or 0)
            if available <= 0:
                continue
            take = min(available, remaining)
            lines.append(
                warehouse_repository.PickLine(
                    hardware_category=cat,
                    product_code=code,
                    inventory_location_id=row.id,
                    quantity=take,
                )
            )
            remaining -= take
    return lines


def pick_pull(
    session: Session,
    pr_id: uuid.UUID,
    picked_by: str = "picker",
    *,
    cap: dict[tuple[str, str], int] | None = None,
):
    """Start the pick (if the pull is still pending) and confirm it off whatever stock exists.

    Returns the `ConfirmPickResult`, so a caller can assert on `outcome` ("PICKED" / "SHORT") and
    `shortfalls` the way it used to assert on the approve tuple.
    """
    pr = warehouse_repository.get_pull_request_details(session, pr_id)
    if pr.status == PullRequestStatus.PENDING:
        warehouse_repository.start_pull_request_pick(session, pr_id, picked_by)
        session.flush()
        pr = warehouse_repository.get_pull_request_details(session, pr_id)

    result = warehouse_repository.confirm_pick(session, pr_id, build_pick_lines(session, pr, cap=cap), picked_by)
    session.flush()
    return result
