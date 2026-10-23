"""Editing a draft while its GP registration is live (#1903).

The registration's save writes back the project and lines it sent to GP, so a change made while GP is
answering - a project picked in another window on a draft with none - left GP's job and Nexus's apart.
"""

import uuid
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from app.errors import ConflictError
from app.models.enums import POStatus
from app.repositories import gp_outbox_repository
from app.repositories import po_repository as repo


class _Session:
    def __init__(self, ledger=None):
        self.ledger = ledger

    def get(self, _model, _key):
        return self.ledger


def _draft(*, since):
    return SimpleNamespace(id=uuid.uuid4(), status=POStatus.DRAFT, registering_key="k1", registering_since=since)


@pytest.fixture(autouse=True)
def _nothing_queued(monkeypatch):
    monkeypatch.setattr(gp_outbox_repository, "queued_po_registration", lambda session, po_id: None)


def test_an_edit_is_refused_while_a_registration_waits_on_gp():
    with pytest.raises(ConflictError, match="being registered in GP right now"):
        repo._refuse_while_registration_queued(_Session(), _draft(since=datetime.utcnow()))


def test_an_edit_is_refused_when_gp_answered_a_registration_never_recorded():
    answered = SimpleNamespace(relay_result={"po_number": "PO1"}, result_id=None)
    stale = datetime.utcnow() - timedelta(seconds=repo.REGISTRATION_CLAIM_SECONDS + 60)
    # It never clears on its own, so it does not say to come back in a moment (#1950): Register finishes it.
    with pytest.raises(ConflictError, match="Reopen Register on this PO") as exc:
        repo._refuse_while_registration_queued(_Session(ledger=answered), _draft(since=stale))
    assert "in a moment" not in str(exc.value)


def test_a_stale_claim_gp_never_answered_lets_the_edit_through():
    stale = datetime.utcnow() - timedelta(seconds=repo.REGISTRATION_CLAIM_SECONDS + 60)
    repo._refuse_while_registration_queued(_Session(), _draft(since=stale))
