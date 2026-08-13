"""Derive the "returned to Pending" note a cancelled pull leaves on its source request (#613).

Cancelling a pull sends its source request back to PENDING for re-acceptance and leaves the request
still pointing at the now-CANCELLED pull (see
`warehouse.pull_requests._return_source_request_to_pending`). Without that explanation a request the
user thought they had dispatched simply reappears on the accept board days later; the accept queue
reads this note to say where it came from.

Purely derived - no column stores it - so a re-accept, which overwrites `pull_request_id` with the
fresh pull it mints, clears the note for free. Shared verbatim by the shop-assembly and shipping-out
request lists, which raise the identical question.
"""

import uuid

from sqlalchemy import select

from app.models.enums import PullRequestStatus
from app.models.pull_request import PullRequest as PullRequestModel


def return_notes_for(session, pending_requests) -> dict[uuid.UUID, str | None]:
    """A note per request whose minted pull is CANCELLED, None for the rest, in ONE query for the
    whole list (CLAUDE.md perf rules).

    `pending_requests` must already be filtered to PENDING requests - the note only belongs on the
    accept board, and an APPROVED request never points at a cancelled pull while a REJECTED one is
    off the board. Each request must expose `id` and `pull_request_id`.
    """
    notes: dict[uuid.UUID, str | None] = {r.id: None for r in pending_requests}
    pull_ids = {r.pull_request_id for r in pending_requests if r.pull_request_id is not None}
    if not pull_ids:
        return notes

    cancelled: dict[uuid.UUID, tuple] = {
        pid: (number, cancelled_by, cancelled_at, reason)
        for pid, number, status, cancelled_by, cancelled_at, reason in session.execute(
            select(
                PullRequestModel.id,
                PullRequestModel.request_number,
                PullRequestModel.status,
                PullRequestModel.cancelled_by,
                PullRequestModel.cancelled_at,
                PullRequestModel.cancellation_reason,
            ).where(PullRequestModel.id.in_(pull_ids))
        ).all()
        if status == PullRequestStatus.CANCELLED
    }

    for request in pending_requests:
        meta = cancelled.get(request.pull_request_id)
        if meta is not None:
            notes[request.id] = _format_note(*meta)
    return notes


def _format_note(request_number: str, cancelled_by: str | None, cancelled_at, reason: str | None) -> str:
    who = cancelled_by or "someone"
    when = cancelled_at.date().isoformat() if cancelled_at is not None else "an earlier date"
    head = f"Returned to Pending: pull {request_number} was cancelled by {who} on {when}"
    return f"{head}: {reason}" if reason else f"{head}."
