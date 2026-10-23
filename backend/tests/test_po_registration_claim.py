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
from tests.test_register_po_in_gp import (
    _delete_queued_write,
    _queued_write,
    _run_register,
    _stock_draft_po,
    _stub_the_register_resolvers_world,
)


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


def test_a_registration_gp_took_that_failed_to_save_is_queued_from_what_gp_was_sent(monkeypatch, db_session):
    """#1950: the attempt's key lived only in the dialog that pushed it, so once that closed nothing could
    finish the PO GP had made. It is queued under the same key with what GP was sent; the held writes
    panel's Retry saves it from there, and the queued row holds the draft in place of the claim."""
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())

    async def _relay_call(company, op, payload=None, timeout=None):
        return {"po_number": "0001275", "company": "TUBC"}

    def _persist_fails(**kw):
        raise RuntimeError("database went away")

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    monkeypatch.setattr(po_schema, "_persist_register_po", _persist_fails)
    try:
        with pytest.raises(RuntimeError):
            _run_register(draft, key)

        queued = _queued_write(key)
        assert (queued["op"], queued["status"], queued["maybe_in_gp"]) == ("register_po_in_gp", "PENDING", True)
        assert queued["persist_context"]["po_id"] == str(draft.id)
        assert queued["persist_context"]["line_items_data"][0]["unit_cost"] == float(draft.line_items[0].unit_cost)
        assert po_repository.reload_po(db_session, draft.id).registering_key is None
        # Another window is refused by the queued row rather than pushing a second PO.
        with pytest.raises(InvalidStateTransitionError, match="queued"):
            po_repository.claim_po_registration(db_session, draft.id, str(uuid.uuid4()))
    finally:
        _delete_queued_write(key)


def test_the_claim_is_kept_when_the_registration_gp_took_could_not_be_queued(monkeypatch, db_session):
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())

    async def _relay_call(company, op, payload=None, timeout=None):
        return {"po_number": "0001275", "company": "TUBC"}

    def _persist_fails(**kw):
        raise RuntimeError("database went away")

    def _queue_fails(**kw):
        raise RuntimeError("still away")

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    monkeypatch.setattr(po_schema, "_persist_register_po", _persist_fails)
    monkeypatch.setattr(po_schema.gp_outbox_enqueue, "enqueue", _queue_fails)
    with pytest.raises(RuntimeError, match="database went away"):
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


def _held_write(session, draft, key, *, status="FAILED", unit_cost=7.25):
    """The registration held under `key`, carrying what GP was sent: the draft's line at `unit_cost`."""
    from app.repositories import gp_outbox_repository

    line = draft.line_items[0]
    row = gp_outbox_repository.enqueue(
        session,
        idempotency_key=key,
        op="register_po_in_gp",
        relay_op="create_po",
        company="TUBC",
        payload={"header": {}},
        persist_context={
            "po_id": str(draft.id),
            "gp_vendor_id": "GPV1",
            "vendor_name_snapshot": "GP Vendor",
            "line_items_data": [
                {
                    "id": str(line.id),
                    "hardware_category": line.hardware_category,
                    "product_code": line.product_code,
                    "ordered_quantity": line.ordered_quantity,
                    "unit_cost": unit_cost,
                    "classification": None,
                    "order_as": None,
                    "custom_inventory_item_id": None,
                    "cost_code": None,
                    "uofm": None,
                    "job_cost": None,
                }
            ],
            "cost_code": None,
            "buyer_id": "mira",
            "shipping_cost": None,
            "tariff_amount": None,
            "project_id": None,
        },
        entity_key=f"po:{draft.id}",
        label="Register PO in GP",
        maybe_in_gp=True,
    )
    row.status = status
    row.failure_kind = "persist_failed" if status == "FAILED" else None
    session.flush()
    return row


def _resume_world(monkeypatch, db_session, key, po_number):
    from app.services.gp_idempotency import IdempotencyState

    pushes: list[str] = []

    async def _relay_call(company, op, payload=None, timeout=None):
        pushes.append(op)
        return {"po_number": "unused", "company": "TUBC"}

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    answered = IdempotencyState(
        op="register_po_in_gp", relay_result={"po_number": po_number, "company": "TUBC"}, result_id=None
    )
    # GP answered this attempt earlier; its persist failed then.
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda k: answered if k == key else None)
    return pushes


def test_the_original_attempt_resumes_from_what_gp_was_sent_without_pushing_again(monkeypatch, db_session):
    """#1950: the resume saved this call's form over GP's answer. The form is sent at the draft's 10.00;
    GP was sent 7.25, and that is what is recorded."""
    from app.models.gp_outbox import GpWriteOutbox

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes = _resume_world(monkeypatch, db_session, key, "0001291")
    po_repository.claim_po_registration(db_session, draft.id, key)
    _ledger(db_session, key, po_number="0001291")
    held = _held_write(db_session, draft, key)

    result = _run_register(draft, key)
    assert pushes == []  # nothing sent to GP again
    assert result.purchase_order.po_number == "0001291"
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.GP_REGISTERED
    assert po.registering_key is None
    assert [float(li.unit_cost) for li in po.line_items] == [7.25]
    # The held write is finished, not left asking to be retried.
    assert db_session.get(GpWriteOutbox, held.id).status == "SUCCEEDED"


def test_a_resume_with_no_held_write_saves_from_this_calls_context(monkeypatch, db_session):
    """#1950 review: a key whose save and queueing both failed, or a ledger answer from before #1950, has no
    held write. Refusing it held the draft behind an answer nothing could finish; the attempt's own resume
    saves from what it sends, without pushing again."""
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes = _resume_world(monkeypatch, db_session, key, "0001292")
    po_repository.claim_po_registration(db_session, draft.id, key)
    _ledger(db_session, key, po_number="0001292")

    result = _run_register(draft, key)
    assert pushes == []
    assert result.queued is False
    assert result.purchase_order.po_number == "0001292"
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.GP_REGISTERED
    assert po.registering_key is None
    assert [float(li.unit_cost) for li in po.line_items] == [10.0]


def test_a_resume_with_no_held_write_that_fails_to_save_is_held_for_retry(monkeypatch, db_session):
    """And when that save fails too, it is queued under the key as a fresh push's is, so the held writes
    panel's Retry finishes it; a queue that is also down leaves the claim for the next resume."""
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes = _resume_world(monkeypatch, db_session, key, "0001294")
    po_repository.claim_po_registration(db_session, draft.id, key)
    _ledger(db_session, key, po_number="0001294")

    def _persist_fails(**kw):
        raise RuntimeError("database went away")

    monkeypatch.setattr(po_schema, "_persist_register_po", _persist_fails)
    try:
        with pytest.raises(RuntimeError, match="database went away"):
            _run_register(draft, key)
        queued = _queued_write(key)
        assert (queued["status"], queued["maybe_in_gp"]) == ("PENDING", True)
        assert queued["persist_context"]["po_id"] == str(draft.id)
        assert pushes == []
        assert po_repository.reload_po(db_session, draft.id).registering_key is None
    finally:
        _delete_queued_write(key)


def test_a_resume_while_the_queue_is_finishing_it_answers_queued(monkeypatch, db_session):
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes = _resume_world(monkeypatch, db_session, key, "0001293")
    _ledger(db_session, key, po_number="0001293")
    held = _held_write(db_session, draft, key, status="PENDING")

    result = _run_register(draft, key)
    assert result.queued is True
    assert result.outbox_entry_id == str(held.id)
    assert pushes == []
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.DRAFT
    assert po.registering_key is None


def test_a_resume_refuses_a_ledger_row_another_kind_of_write_made(monkeypatch, db_session):
    """#1873: the resume persisted any row's relay_result as this registration's - a receipt's answer
    included - registering the draft under a PO GP never made for it. Refused before anything is sent."""
    from app.errors import ValidationError
    from app.services.gp_idempotency import IdempotencyState

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes: list[str] = []

    async def _relay_call(company, op, payload=None, timeout=None):
        pushes.append(op)
        return {"po_number": "unused", "company": "TUBC"}

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    receipt = IdempotencyState(op="create_receive", relay_result={"receipt_number": "RCT000777"}, result_id=None)
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda k: receipt if k == key else None)

    with pytest.raises(ValidationError) as excinfo:
        _run_register(draft, key)

    assert excinfo.value.field == "idempotency_key"
    assert pushes == []
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.DRAFT
    assert po.registering_key is None


def test_a_finished_key_answers_only_for_the_po_it_registered(monkeypatch, db_session):
    """#1905: sent with another PO's id, a key that already registered a PO handed that PO back."""
    from app.errors import ValidationError
    from app.services.gp_idempotency import IdempotencyState

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes: list[str] = []

    async def _relay_call(company, op, payload=None, timeout=None):
        pushes.append(op)
        return {"po_number": "unused", "company": "TUBC"}

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    finished = IdempotencyState(
        op="register_po_in_gp", relay_result={"po_number": "0001300"}, result_id=str(uuid.uuid4())
    )
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda k: finished if k == key else None)

    with pytest.raises(ValidationError) as excinfo:
        _run_register(draft, key)

    assert excinfo.value.field == "idempotency_key"
    assert pushes == []


# --- #1950: a GP answer Nexus never saved, with no held write to finish it -------------------------------


def test_the_po_hands_back_the_claim_key_of_a_gp_answer_nexus_never_saved(db_session):
    """The key lived only in the dialog's ref, so once that closed nothing could resume the attempt. The PO
    says it now - only while the draft is held by that unrecorded answer - with GP's number for it."""
    from app.schemas.converters import po_to_type

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    po_repository.claim_po_registration(db_session, draft.id, key)
    assert po_to_type(po_repository.reload_po(db_session, draft.id)).registering_key is None  # just on its way

    _ledger(db_session, key, po_number="0001950")
    shown = po_to_type(po_repository.reload_po(db_session, draft.id))
    assert (shown.registering_key, shown.registering_gp_po_number) == (key, "0001950")

    draft.status = POStatus.CANCELLED
    db_session.flush()
    assert po_to_type(po_repository.reload_po(db_session, draft.id)).registering_key is None


def test_a_fresh_push_keeps_what_it_sent_beside_gps_answer(monkeypatch, db_session):
    draft = _stock_draft_po(db_session)
    recorded: dict = {}

    async def _relay_call(company, op, payload=None, timeout=None):
        return {"po_number": "0001951", "company": "TUBC"}

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    monkeypatch.setattr(po_schema.gp_idempotency, "record_relay_result", lambda k, op, r: recorded.update(r))
    _run_register(draft, str(uuid.uuid4()))

    assert recorded["po_number"] == "0001951"
    pushed = recorded[po_schema.PUSHED_CONTEXT_KEY]
    assert pushed["po_id"] == str(draft.id)
    assert pushed["line_items_data"][0]["unit_cost"] == float(draft.line_items[0].unit_cost)


def test_a_resume_with_no_held_write_saves_what_gp_was_sent_not_the_reopened_form(monkeypatch, db_session):
    """Reopened on the draft, the dialog sends the form again under the claim's key - a form the person could
    have edited. GP was sent 7.25 and the form says 10.00: what GP was sent is what is saved."""
    from app.services.gp_idempotency import IdempotencyState

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes = _resume_world(monkeypatch, db_session, key, "0001952")
    po_repository.claim_po_registration(db_session, draft.id, key)
    _ledger(db_session, key, po_number="0001952")
    line = draft.line_items[0]
    pushed = {
        "po_id": str(draft.id),
        "gp_vendor_id": "GPV1",
        "vendor_name_snapshot": "GP Vendor",
        "line_items_data": [
            {
                "id": str(line.id),
                "hardware_category": line.hardware_category,
                "product_code": line.product_code,
                "ordered_quantity": line.ordered_quantity,
                "unit_cost": 7.25,
                "classification": None,
                "order_as": None,
                "custom_inventory_item_id": None,
                "cost_code": None,
                "uofm": None,
                "job_cost": None,
            }
        ],
        "cost_code": None,
        "buyer_id": "mira",
        "shipping_cost": None,
        "tariff_amount": None,
        "project_id": None,
    }
    answered = IdempotencyState(
        op="register_po_in_gp",
        relay_result={"po_number": "0001952", "company": "TUBC", po_schema.PUSHED_CONTEXT_KEY: pushed},
        result_id=None,
    )
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda k: answered if k == key else None)

    result = _run_register(draft, key)

    assert pushes == []
    assert result.purchase_order.po_number == "0001952"
    po = po_repository.reload_po(db_session, draft.id)
    assert po.status == POStatus.GP_REGISTERED
    assert [float(li.unit_cost) for li in po.line_items] == [7.25]


# --- #1962: a key GP answered resumes only the registration it answered ----------------------------------


def test_a_key_gp_answered_for_one_draft_cannot_claim_another(db_session):
    """Any draft with no claim took a key GP had already answered for another, and the resume then saved that
    answer onto it. The answer is a draft's only while its claim is under the key or a write is held under it."""
    from app.errors import ValidationError

    answered = _stock_draft_po(db_session)
    other = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    po_repository.claim_po_registration(db_session, answered.id, key)
    _ledger(db_session, key, po_number="0001962")

    with pytest.raises(ValidationError, match="already used for another PO") as e:
        po_repository.claim_po_registration(db_session, other.id, key)
    assert e.value.field == "idempotency_key"
    db_session.refresh(other)
    assert other.registering_key is None

    # The draft it answered still takes it again, to resume.
    po_repository.claim_po_registration(db_session, answered.id, key)
    assert answered.registering_key == key


def test_a_key_whose_kept_context_names_another_po_cannot_claim_this_one(db_session):
    from app.errors import ValidationError
    from app.models.gp_write import GpWriteIdempotency

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    po_repository.claim_po_registration(db_session, draft.id, key)
    db_session.add(
        GpWriteIdempotency(
            key=key,
            op="register_po_in_gp",
            relay_result={
                "po_number": "0001962",
                "company": "TUBC",
                po_schema.PUSHED_CONTEXT_KEY: {"po_id": str(uuid.uuid4())},
            },
        )
    )
    db_session.flush()

    with pytest.raises(ValidationError, match="already used for another PO"):
        po_repository.claim_po_registration(db_session, draft.id, key)


def test_a_resume_whose_answer_belongs_to_another_po_is_refused_and_saves_nothing(monkeypatch, db_session):
    """The tenant hole (#1962): with no held write the resume saved the context kept with the answer, which
    names its own PO, so a key from another company's answered attempt, sent with the caller's own PO, marked
    that company's draft registered and handed it back. Refused before anything is claimed or saved."""
    from app.errors import ValidationError
    from app.services.gp_idempotency import IdempotencyState

    theirs = _stock_draft_po(db_session)
    ours = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    pushes = _resume_world(monkeypatch, db_session, key, "0001962")
    answered = IdempotencyState(
        op="register_po_in_gp",
        relay_result={
            "po_number": "0001962",
            "company": "TUBC",
            po_schema.PUSHED_CONTEXT_KEY: {"po_id": str(theirs.id), "line_items_data": []},
        },
        result_id=None,
    )
    monkeypatch.setattr(po_schema.gp_idempotency, "load", lambda k: answered if k == key else None)

    with pytest.raises(ValidationError, match="already used for another PO") as e:
        _run_register(ours, key)

    assert e.value.field == "idempotency_key"
    assert pushes == []
    for draft in (theirs, ours):
        po = po_repository.reload_po(db_session, draft.id)
        assert po.status == POStatus.DRAFT
        assert po.registering_key is None


def test_the_unrecorded_answers_refusals_say_to_reopen_register(db_session):
    """Since #1950 the way out is reopening Register on the PO, not the window that started it (#1962)."""
    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    po_repository.claim_po_registration(db_session, draft.id, key)
    _ledger(db_session, key, po_number="0001963")

    with pytest.raises(InvalidStateTransitionError, match="Reopen Register on this PO"):
        po_repository.cancel_po(db_session, draft.id)
    with pytest.raises(InvalidStateTransitionError, match="Reopen Register on this PO"):
        po_repository.claim_po_registration(db_session, draft.id, str(uuid.uuid4()))


# --- #1849: the draft is claimed before it is read for its digest ----------------------------------------


def test_the_draft_is_claimed_in_the_pre_flight_that_reads_its_digest(monkeypatch, db_session):
    """The digest was read before the claim was taken, so an edit could land between them: the queued
    payload was then refused as a changed draft, though GP may already have taken it. Taken together now."""
    from app.errors import ConflictError
    from tests.test_register_po_in_gp import _register_line, _use_test_session

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    _use_test_session(monkeypatch, db_session)
    digest: dict = {}

    po_schema._prepare_register_po(
        po_id=draft.id,
        gp_vendor_id="GPV1",
        buyer_id="mira",
        cost_code=None,
        line_items_data=[_register_line("HINGE", "HG-100", "ALIAS-100")],
        site="VANCOUVER",
        idempotency_key=key,
        digest_out=digest,
        claim=True,
    )

    assert po_repository.reload_po(db_session, draft.id).registering_key == key
    with pytest.raises(ConflictError, match="being registered in GP right now"):
        po_repository.update_po(db_session, draft.id, shipping_cost=85)
    assert digest["registration_digest"] == po_repository.registration_digest(db_session, draft.id)


def test_an_edit_during_the_relay_attempt_is_refused_so_the_queued_registration_is_not_stale(monkeypatch, db_session):
    from app.errors import ConflictError, RelayTimeoutError
    from tests.test_register_po_in_gp import _delete_queued_write, _queued_write

    draft = _stock_draft_po(db_session)
    key = str(uuid.uuid4())
    edits: list[str] = []

    async def _relay_call(company, op, payload=None, timeout=None):
        try:
            po_repository.update_po(db_session, draft.id, shipping_cost=85)
            edits.append("saved")
        except ConflictError:
            edits.append("refused")
        raise RelayTimeoutError()

    _stub_the_register_resolvers_world(monkeypatch, db_session, relay_call=_relay_call)
    try:
        result = _run_register(draft, key)

        assert result.queued is True
        assert edits == ["refused"]
        queued = _queued_write(key)
        assert queued["maybe_in_gp"] is True
        assert queued["persist_context"]["registration_digest"] == po_repository.registration_digest(
            db_session, draft.id
        )
    finally:
        _delete_queued_write(key)
