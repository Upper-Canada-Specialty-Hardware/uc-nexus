"""A keyed receipt GP refused after an attempt that may have reached it (#1849).

The flag holds a draft that may already be in GP. A keyed receipt's retry is looked up by its key
before anything else, so a refusal on that retry says GP holds no receipt under it: the draft goes
back for review, and is not stuck approved for good.
"""

from types import SimpleNamespace

from app.repositories.warehouse import receive_drafts

_KEYED = {"po_number": "0000123", "idempotency_key": "a1b2c3d4-key"}


class _Session:
    def get(self, _model, _key):
        return None


def _row(**overrides):
    row = dict(
        op="create_receive",
        relay_op="create_receipt",
        status="FAILED",
        failure_kind="gp_rejected",
        maybe_in_gp=True,
        payload=_KEYED,
        idempotency_key="k",
    )
    row.update(overrides)
    return SimpleNamespace(**row)


def test_a_keyed_receipt_gp_refused_after_its_key_was_looked_up_is_released():
    assert receive_drafts.outbox_entry_never_reached_gp(_Session(), _row()) is True


def test_one_that_may_be_in_gp_and_ran_out_of_attempts_is_not():
    assert receive_drafts.outbox_entry_never_reached_gp(_Session(), _row(failure_kind="exhausted")) is False


def test_an_unkeyed_one_is_not():
    assert receive_drafts.outbox_entry_never_reached_gp(_Session(), _row(payload={"po_number": "1"})) is False
