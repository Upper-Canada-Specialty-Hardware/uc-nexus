"""A failed registration GP took, or may have, keeps holding its draft (#1948).

Only a waiting registration (PENDING or IN_FLIGHT) used to hold the draft. One that FAILED after GP
answered (its save failed) or after an attempt that may have reached GP freed the draft to be cancelled -
a GP PO Nexus has no row for - or registered again under a fresh key - a second GP PO. Never touches GP."""

import uuid
from datetime import datetime, timedelta

import pytest

from app.errors import ConflictError, InvalidStateTransitionError
from app.models.enums import POStatus
from app.models.gp_write import GpWriteIdempotency
from app.repositories import gp_outbox_repository, po_repository
from tests.test_po_queued_registration import _po, _queue_registration


def _failed_registration(
    session, po_id, *, kind="persist_failed", maybe_in_gp=False, relay_result=None, result_id=None
):
    key = str(uuid.uuid4())
    row = _queue_registration(session, po_id, key=key, status="FAILED")
    row.failure_kind = kind
    row.maybe_in_gp = maybe_in_gp
    if relay_result is not None or result_id is not None:
        session.add(GpWriteIdempotency(key=key, op="register_po_in_gp", relay_result=relay_result, result_id=result_id))
    session.flush()
    return row


GP_ANSWERED = {"po_number": "0001948", "company": "TUBC"}


@pytest.mark.parametrize(
    ("kind", "maybe_in_gp", "relay_result"),
    [
        ("persist_failed", False, GP_ANSWERED),  # GP made it; the save after failed
        ("exhausted", True, None),  # timed out until the budget ran out
        ("ambiguous", True, None),
    ],
    ids=["gp-answered", "exhausted-maybe-in-gp", "ambiguous"],
)
def test_a_failed_registration_gp_holds_or_may_hold_keeps_its_draft(db_session, kind, maybe_in_gp, relay_result):
    po = _po(db_session)
    row = _failed_registration(db_session, po.id, kind=kind, maybe_in_gp=maybe_in_gp, relay_result=relay_result)

    assert gp_outbox_repository.queued_po_registration(db_session, po.id).id == row.id
    assert gp_outbox_repository.registration_holds_draft(db_session, row)

    with pytest.raises(InvalidStateTransitionError, match="Retry on the held GP writes panel"):
        po_repository.cancel_po(db_session, po.id)
    with pytest.raises(InvalidStateTransitionError, match="Retry on the held GP writes panel"):
        po_repository.claim_po_registration(db_session, po.id, str(uuid.uuid4()))
    with pytest.raises(ConflictError, match="Retry on the held GP writes panel"):
        po_repository.update_po(db_session, po.id, shipping_cost=85)
    assert po.status == POStatus.DRAFT
    assert po.deleted_at is None


@pytest.mark.parametrize(
    ("kind", "maybe_in_gp", "relay_result", "result_id"),
    [
        ("gp_rejected", False, None, None),  # GP said no: nothing reached it
        ("gp_rejected", True, None, None),  # refused after the relay looked the key up and found no PO
        ("po_changed", False, None, None),  # held before the push, nothing sent
        ("persist_failed", True, GP_ANSWERED, "finished"),  # finished since: the ledger has the record
    ],
    ids=["rejected", "rejected-after-lookup", "changed-before-push", "finished"],
)
def test_a_failed_registration_nothing_reached_gp_with_frees_its_draft(
    db_session, kind, maybe_in_gp, relay_result, result_id
):
    po = _po(db_session)
    row = _failed_registration(
        db_session, po.id, kind=kind, maybe_in_gp=maybe_in_gp, relay_result=relay_result, result_id=result_id
    )

    assert gp_outbox_repository.queued_po_registration(db_session, po.id) is None
    assert not gp_outbox_repository.registration_holds_draft(db_session, row)
    assert po_repository.cancel_po(db_session, po.id).status == POStatus.CANCELLED


def test_the_attempts_own_key_still_passes_its_held_row(db_session):
    """The same attempt retried under its key is let through, to finish from what GP was sent (#1950)."""
    po = _po(db_session)
    row = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED)
    assert gp_outbox_repository.queued_po_registration(db_session, po.id, exclude_key=row.idempotency_key) is None


def test_a_waiting_registration_keeps_its_own_words(db_session):
    po = _po(db_session)
    _failed_registration(db_session, po.id, relay_result=GP_ANSWERED)
    _queue_registration(db_session, po.id)
    with pytest.raises(InvalidStateTransitionError, match="queued for GP"):
        po_repository.cancel_po(db_session, po.id)


def test_the_list_says_which_registrations_hold_their_draft_in_one_read(db_session):
    po = _po(db_session)
    held = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED)
    freed = _failed_registration(db_session, po.id, kind="gp_rejected")
    waiting = _queue_registration(db_session, po.id)

    holding = gp_outbox_repository.registrations_holding_drafts(db_session, [held, freed, waiting])
    assert holding == {held.id, waiting.id}


def test_retry_is_refused_while_a_window_is_registering_the_po(db_session):
    po = _po(db_session)
    row = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED)
    po.registering_key = row.idempotency_key
    po.registering_since = datetime.utcnow()
    db_session.flush()

    with pytest.raises(ConflictError, match="being registered in GP from a window"):
        gp_outbox_repository.retry_entry(db_session, row.id)
    assert row.status == "FAILED"

    # A claim gone stale is a window that is no longer there.
    po.registering_since = datetime.utcnow() - timedelta(seconds=po_repository.REGISTRATION_CLAIM_SECONDS + 1)
    db_session.flush()
    assert gp_outbox_repository.retry_entry(db_session, row.id).status == "PENDING"
