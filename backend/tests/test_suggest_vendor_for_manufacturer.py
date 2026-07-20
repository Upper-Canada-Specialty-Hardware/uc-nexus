"""Query.suggest_vendor_for_manufacturer (issue #232): saved-mapping hit vs ranked live vendors.

Follows test_gp_relay_reads.py: resolvers exercised directly with require_user monkeypatched out. The
mapping lookup is patched so these run without a DB - the resolver only opens a session to call lookup,
which never issues a query here."""

import asyncio

import pytest

from app.repositories import manufacturer_vendor_map_repository as map_repo
from app.schemas import relay as relay_module
from app.schemas.queries import Query


class FakeInfo:
    context = {"request": None}


@pytest.fixture(autouse=True)
def _bypass_require_user(monkeypatch):
    monkeypatch.setattr(relay_module, "require_user", lambda info: {"user_id": "test-user"})


class FakeGateway:
    def __init__(self, result):
        self.result = result
        self.calls: list[tuple] = []

    async def relay_call(self, company, op, payload=None, timeout=None):
        self.calls.append((company, op, payload))
        return self.result


class _FakeMapping:
    def __init__(self, gp_vendor_id, gp_vendor_name):
        self.gp_vendor_id = gp_vendor_id
        self.gp_vendor_name = gp_vendor_name


def test_saved_mapping_hit_returns_that_vendor_and_skips_relay(monkeypatch):
    captured = {}

    def fake_lookup(session, gp_company, manufacturer_key):
        captured["company"] = gp_company
        captured["key"] = manufacturer_key
        return _FakeMapping("GPV9", "Saved Vendor")

    monkeypatch.setattr(map_repo, "lookup", fake_lookup)
    gateway = FakeGateway({"vendors": []})
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)

    async def run():
        return await Query().suggest_vendor_for_manufacturer(FakeInfo(), gp_company="TUBC", manufacturer="Acme, Inc.")

    suggestion = asyncio.run(run())

    assert suggestion.saved_mapping is True
    assert len(suggestion.candidates) == 1
    assert suggestion.candidates[0].gp_vendor_id == "GPV9"
    assert suggestion.candidates[0].gp_vendor_name == "Saved Vendor"
    assert suggestion.candidates[0].score == 100.0
    # lookup is keyed by the normalized manufacturer, and a mapping hit must not hit the relay.
    assert captured == {"company": "TUBC", "key": "ACME"}
    assert gateway.calls == []


def test_no_mapping_ranks_live_vendors_by_fuzzy_score(monkeypatch):
    monkeypatch.setattr(map_repo, "lookup", lambda session, gp_company, manufacturer_key: None)
    gateway = FakeGateway(
        {
            "vendors": [
                {"vendor_id": "V1", "vendor_name": "Acme Inc", "vendor_class": "HW", "status": 1},
                {"vendor_id": "V2", "vendor_name": "Schlage Lock Company", "vendor_class": "HW", "status": 1},
                {"vendor_id": "V3", "vendor_name": "Best Access", "vendor_class": "HW", "status": 1},
            ]
        }
    )
    monkeypatch.setattr(relay_module, "relay_gateway", gateway)

    async def run():
        return await Query().suggest_vendor_for_manufacturer(FakeInfo(), gp_company="TUBC", manufacturer="Acme")

    suggestion = asyncio.run(run())

    assert suggestion.saved_mapping is False
    assert suggestion.candidates  # non-empty
    top = suggestion.candidates[0]
    assert top.gp_vendor_id == "V1"  # "Acme Inc" ~ "Acme"
    assert top.score == 100.0
    # ordered best-first
    scores = [c.score for c in suggestion.candidates]
    assert scores == sorted(scores, reverse=True)
    assert gateway.calls == [("TUBC", "list_vendors", None)]
