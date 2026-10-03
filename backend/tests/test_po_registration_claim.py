"""One registration attempt per draft at a time (#1274).

Two windows registering one draft with the relay up each pushed create_po under their own key, and the
relay's per-key protection cannot tell two keys apart, so GP made two POs. Never touches GP: the relay
call is stubbed, as in the register tests these share their setup with."""

import uuid
from datetime import datetime, timedelta

import pytest

from app.errors import InvalidStateTransitionError, RelayCallError
from app.models.enums import POStatus
from app.repositories import po_repository
from app.schemas import po as po_schema
from tests.test_register_po_in_gp import _run_register, _stock_draft_po, _stub_the_register_resolvers_world


def _register_input(draft, key):
    from app.schemas.inputs import RegisterPOInput, RegisterPOLineItemInput

    line = draft.line_items[0]
    return RegisterPOInput(
        po_id=str(draft.id),
        gp_vendor_id="GPV1",
        gp_vendor_name="GP Vendor",
        gp_company="TUBC",
        buyer_id="mira",
        line_items=[
            RegisterPOLineItemInput(
                id=str(line.id),
                hardware_category=line.hardware_category,
                product_code=line.product_code,
                ordered_quantity=line.ordered_quantity,
                unit_cost=float(line.unit_cost),
            )
        ],
        idempotency_key=key,
        site="VANCOUVER",
    )


def test_a_second_window_is_refused_while_the_first_is_on_its_way_to_gp(monkeypatch, db_session):
    """Relay up. While the first window's create_po is out at GP, a second window tries the same draft
    under its own key and is refused before it sends anything; the first then completes."""
    draft = _stock_draft_po(db_session)
    pushes: list[str] = []
    second: dict = {}

    async def _relay_call(company, op, payload=None, timeout=None):
        pushes.append(op)
        if not second:
            try:
                await po_schema.POMutations().register_po_in_gp(None, _register_input(draft, str(uuid.uuid4())))
                second["outcome"] = "registered"
            except InvalidStateTransitionError as e:
                second["outcome"] = e.message
        return {"po_number": "0001274", "company": "TUBC"}

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    result = _run_register(draft, str(uuid.uuid4()))

    assert "another window" in second["outcome"]
    assert pushes == ["create_po"]  # the second window sent nothing
    assert result.queued is False
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.GP_REGISTERED
    assert po.registering_key is None  # settled, so released


def test_the_claim_is_released_when_gp_refuses(monkeypatch, db_session):
    draft = _stock_draft_po(db_session)

    async def _relay_call(company, op, payload=None, timeout=None):
        raise RelayCallError("vendor on hold")

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    with pytest.raises(RelayCallError):
        _run_register(draft, str(uuid.uuid4()))
    assert po_repository.reload_po(db_session, draft.id).registering_key is None


def test_the_claim_is_kept_when_gp_may_hold_the_po_but_nexus_did_not_record_it(monkeypatch, db_session):
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())

    async def _relay_call(company, op, payload=None, timeout=None):
        return {"po_number": "0001275", "company": "TUBC"}

    def _persist_fails(**kw):
        raise RuntimeError("database went away")

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    monkeypatch.setattr(po_schema, "_persist_register_po", _persist_fails)
    with pytest.raises(RuntimeError):
        _run_register(draft, key)
    assert po_repository.reload_po(db_session, draft.id).registering_key == key
    # Another window waits until it goes stale rather than pushing a second PO.
    with pytest.raises(InvalidStateTransitionError, match="another window"):
        po_repository.claim_po_registration(db_session, draft.id, str(uuid.uuid4()))


def test_the_same_attempt_may_retry_and_a_stale_claim_does_not_block(db_session):
    draft = _stock_draft_po(db_session)
    po_repository.claim_po_registration(db_session, draft.id, "attempt-1")
    po_repository.claim_po_registration(db_session, draft.id, "attempt-1")  # the same attempt, retried

    with pytest.raises(InvalidStateTransitionError, match="right now"):
        po_repository.cancel_po(db_session, draft.id)

    draft.registering_since = datetime.utcnow() - timedelta(seconds=po_repository.REGISTRATION_CLAIM_SECONDS + 1)
    db_session.flush()
    po_repository.claim_po_registration(db_session, draft.id, "attempt-2")
    assert draft.registering_key == "attempt-2"

    po_repository.release_po_registration(db_session, draft.id, "attempt-1")  # no longer its claim
    db_session.refresh(draft)
    assert draft.registering_key == "attempt-2"
    po_repository.release_po_registration(db_session, draft.id, "attempt-2")
    db_session.refresh(draft)
    assert draft.registering_key is None


# --- review: a claim whose attempt GP already answered never goes stale ------------------------------


def _ledger(session, key, *, po_number="0009999", result_id=None):
    from app.models.gp_write import GpWriteIdempotency

    session.add(
        GpWriteIdempotency(
            key=key,
            op="register_po_in_gp",
            relay_result={"po_number": po_number, "company": "TUBC"},
            result_id=result_id,
        )
    )
    session.flush()


def test_a_stale_claim_gp_already_answered_still_refuses_another_window(db_session):
    draft = _stock_draft_po(db_session)
    first = str(uuid.uuid4())
    po_repository.claim_po_registration(db_session, draft.id, first)
    _ledger(db_session, first, po_number="0001290")  # GP made the PO; the persist then failed
    draft.registering_since = datetime.utcnow() - timedelta(seconds=po_repository.REGISTRATION_CLAIM_SECONDS * 10)
    db_session.flush()

    with pytest.raises(InvalidStateTransitionError, match="0001290") as e:
        po_repository.claim_po_registration(db_session, draft.id, str(uuid.uuid4()))
    assert "second PO in GP" in e.value.message
    with pytest.raises(InvalidStateTransitionError, match="0001290"):
        po_repository.cancel_po(db_session, draft.id)

    # The attempt itself may take it again and resume through the ledger.
    po_repository.claim_po_registration(db_session, draft.id, first)
    assert draft.registering_key == first


def test_once_the_answer_is_recorded_the_stale_claim_no_longer_blocks(db_session):
    draft = _stock_draft_po(db_session)
    first = str(uuid.uuid4())
    po_repository.claim_po_registration(db_session, draft.id, first)
    _ledger(db_session, first, result_id=str(draft.id))
    draft.registering_since = datetime.utcnow() - timedelta(seconds=po_repository.REGISTRATION_CLAIM_SECONDS + 1)
    db_session.flush()
    po_repository.claim_po_registration(db_session, draft.id, "later")
    assert draft.registering_key == "later"


def test_the_original_attempt_resumes_from_the_ledger_without_pushing_again(monkeypatch, db_session):
    from app.services.gp_idempotency import IdempotencyState

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes: list[str] = []

    async def _relay_call(company, op, payload=None, timeout=None):
        pushes.append(op)
        return {"po_number": "unused", "company": "TUBC"}

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    answered = IdempotencyState(
        op="register_po_in_gp", relay_result={"po_number": "0001291", "company": "TUBC"}, result_id=None
    )
    # GP answered this attempt earlier; its persist failed then.
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda k: answered if k == key else None)
    po_repository.claim_po_registration(db_session, draft.id, key)
    _ledger(db_session, key, po_number="0001291")

    result = _run_register(draft, key)
    assert pushes == []  # nothing sent to GP again
    assert result.purchase_order.po_number == "0001291"
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.GP_REGISTERED
    assert po.registering_key is None
