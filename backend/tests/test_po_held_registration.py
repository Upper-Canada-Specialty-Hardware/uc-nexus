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


def test_the_po_list_reads_the_holding_registrations_however_many_failed_ones_pile_up(db_session):
    """#1948: the list read the newest rows of every registration status and kept the holding ones, so
    the FAILED rows nothing holds pushed a held one past the limit. The server picks them now."""
    po = _po(db_session)
    company = f"T{uuid.uuid4().hex[:6].upper()}"
    held = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED)
    maybe = _failed_registration(db_session, po.id, kind="exhausted", maybe_in_gp=True)
    waiting = _queue_registration(db_session, po.id)
    finished = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED, result_id="done")
    refused = _failed_registration(db_session, po.id, kind="gp_rejected", maybe_in_gp=True)
    freed = [_failed_registration(db_session, po.id, kind="gp_rejected") for _ in range(4)]  # the newest
    for row in [held, maybe, waiting, finished, refused, *freed]:
        row.company = company
    db_session.flush()

    rows = gp_outbox_repository.list_registrations_holding_drafts(db_session, company=company, limit=3)

    assert {r.id for r in rows} == {held.id, maybe.id, waiting.id}


def test_the_list_says_which_writes_gp_took_the_ones_cancel_refuses(db_session):
    """#1948: Cancel was offered on every FAILED row and refused on one GP took. The list says which, off
    one ledger read, so the screen never offers it."""
    po = _po(db_session)
    took = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED)
    maybe = _failed_registration(db_session, po.id, kind="exhausted", maybe_in_gp=True)
    finished = _failed_registration(db_session, po.id, relay_result=GP_ANSWERED, result_id="done")
    rows = [took, maybe, finished]

    assert gp_outbox_repository.writes_gp_took(rows, gp_outbox_repository.ledgers_for(db_session, rows)) == {took.id}
    with pytest.raises(ConflictError, match="GP already took this write"):
        gp_outbox_repository.cancel_entry(db_session, took.id)


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


# --- #1948: a held registration whose GP PO the mirror already copied ---


def _mirrored_copy(session, po_number, *, company="TUBC"):
    from app.models.enums import POOrigin
    from app.models.purchase_order import PurchaseOrder

    copy = PurchaseOrder(
        id=uuid.uuid4(),
        po_number=po_number,
        gp_company=company,
        company=company,
        origin=POOrigin.GP,
        status=POStatus.GP_REGISTERED,
    )
    session.add(copy)
    session.flush()
    return copy


def test_a_held_registration_whose_po_is_already_in_nexus_can_be_let_go_and_its_draft_goes(db_session):
    """GP took it, its save is refused for good (the mirror's copy has a receipt by now), and Retry always
    fails. GP's PO is in Nexus, so cancelling abandons nothing in GP: the row is let go and its draft is
    cancelled with it, so it can never be registered into a second GP PO."""
    po_number = f"P{uuid.uuid4().hex[:8].upper()}"
    po = _po(db_session)
    row = _failed_registration(db_session, po.id, relay_result={"po_number": po_number, "company": "TUBC"})
    _mirrored_copy(db_session, po_number)

    rows = [row]
    ledgers = gp_outbox_repository.ledgers_for(db_session, rows)
    assert gp_outbox_repository.registrations_already_in_nexus(db_session, rows, ledgers) == {row.id: po_number}

    assert gp_outbox_repository.cancel_entry(db_session, row.id).status == "CANCELLED"
    db_session.refresh(po)
    assert po.status == POStatus.CANCELLED
    assert po.deleted_at is not None
    assert gp_outbox_repository.queued_po_registration(db_session, po.id) is None


def test_letting_go_of_a_registration_already_in_nexus_settles_its_ledger_on_the_copy(db_session):
    """#1960: the cancel left the ledger with GP's answer and no record, so the number stayed pending
    registration for good and the mirror skipped the copy on every pass. The ledger now records the copy."""
    from app.repositories.gp_po_sync_repository import po_numbers_pending_registration

    po_number = f"P{uuid.uuid4().hex[:8].upper()}"
    po = _po(db_session)
    row = _failed_registration(db_session, po.id, relay_result={"po_number": po_number, "company": "TUBC"})
    copy = _mirrored_copy(db_session, po_number)
    assert po_number in po_numbers_pending_registration(db_session, "TUBC")

    gp_outbox_repository.cancel_entry(db_session, row.id)

    ledger = db_session.get(GpWriteIdempotency, row.idempotency_key)
    assert ledger.result_id == str(copy.id)
    assert ledger.relay_result["po_number"] == po_number  # GP's answer is kept
    assert po_number not in po_numbers_pending_registration(db_session, "TUBC")
    assert not gp_outbox_repository.write_gp_took(db_session, row)
    assert not gp_outbox_repository.registration_holds_draft(db_session, row)


@pytest.mark.parametrize("where", ["another-company", "cancelled"])
def test_a_held_registration_gp_took_with_no_live_copy_in_its_company_stays_uncancellable(db_session, where):
    po_number = f"P{uuid.uuid4().hex[:8].upper()}"
    po = _po(db_session)
    row = _failed_registration(db_session, po.id, relay_result={"po_number": po_number, "company": "TUBC"})
    copy = _mirrored_copy(db_session, po_number, company="OTHER" if where == "another-company" else "TUBC")
    if where == "cancelled":
        copy.deleted_at = datetime.utcnow()
        db_session.flush()

    with pytest.raises(ConflictError, match="GP already took this write"):
        gp_outbox_repository.cancel_entry(db_session, row.id)
    assert po.status == POStatus.DRAFT
