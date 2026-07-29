"""Multi-backend channels (issue #414).

A Railway PR environment can only exercise a relay-dependent path if a relay dials it, and the relay
used to have exactly one backend URL - so verifying a GP-touching change meant re-pointing the
workstation, which un-pairs it from production. These cover the two halves of the fix: one channel per
configured URL, and a hard company pin on every channel that is not production.

The company pin is the load-bearing part. Test channels serve reads AND writes on purpose, so the only
thing standing between a PR environment and a live GP company is `_dispatch` refusing it.
"""

import asyncio

import pytest

from ucnexus_relay import channel
from ucnexus_relay.config import (
    NON_PRIMARY_ALLOWED_COMPANIES,
    PRODUCTION_BACKEND_URL,
    ChannelCfg,
    channel_allowed_companies,
    get_settings,
    is_primary_backend_url,
)

PR_URL = "wss://backend-pr-414.up.railway.app/relay-link"


# --- config: one URL or many, and which of them is production ------------------------------------


def test_a_bare_string_backend_url_is_still_one_channel():
    # Every config.toml written before #414 holds a bare string. It must keep meaning exactly one
    # channel, or an upgraded relay stops talking to production the moment it restarts.
    assert ChannelCfg(backend_url=PRODUCTION_BACKEND_URL).backend_urls == [PRODUCTION_BACKEND_URL]


def test_a_list_backend_url_is_one_channel_per_entry():
    cfg = ChannelCfg(backend_url=[PRODUCTION_BACKEND_URL, PR_URL])
    assert cfg.backend_urls == [PRODUCTION_BACKEND_URL, PR_URL]


def test_blank_and_empty_backend_url_disable_the_channel():
    assert ChannelCfg(backend_url="").backend_urls == []
    assert ChannelCfg(backend_url=[]).backend_urls == []
    assert ChannelCfg(backend_url=["", "   "]).backend_urls == []


def test_duplicate_urls_collapse_to_one_channel():
    # Two channels to the same backend would fight over its single connection slot, each closing the
    # other with 4409 forever.
    cfg = ChannelCfg(backend_url=[PR_URL, PR_URL + "/", PR_URL.upper()])
    assert cfg.backend_urls == [PR_URL]


def test_the_baked_default_is_production_alone():
    assert ChannelCfg().backend_urls == [PRODUCTION_BACKEND_URL]


def test_primary_is_decided_by_url_not_by_position():
    # Identity, not list order: reordering backend_url must never hand a test backend unrestricted
    # company access.
    assert is_primary_backend_url(PRODUCTION_BACKEND_URL)
    assert not is_primary_backend_url(PR_URL)
    cfg = ChannelCfg(backend_url=[PR_URL, PRODUCTION_BACKEND_URL])
    assert [is_primary_backend_url(u) for u in cfg.backend_urls] == [False, True]


def test_a_cosmetic_url_difference_does_not_demote_production():
    # A trailing slash or stray case in config.toml must not silently pin production to the sandbox.
    assert is_primary_backend_url(PRODUCTION_BACKEND_URL + "/")
    assert is_primary_backend_url(f"  {PRODUCTION_BACKEND_URL.upper()}  ")


def test_a_lookalike_host_is_not_production():
    assert not is_primary_backend_url("wss://backend-production-7866.up.railway.app.evil/relay-link")


def test_only_production_is_unrestricted():
    assert channel_allowed_companies(PRODUCTION_BACKEND_URL) is None
    assert channel_allowed_companies(PR_URL) == NON_PRIMARY_ALLOWED_COMPANIES
    assert channel_allowed_companies("ws://localhost:8000/relay-link") == NON_PRIMARY_ALLOWED_COMPANIES


def test_the_sandbox_pin_is_tubc_only():
    # The whole reason a test channel may write to GP at all. If this list ever grows past the
    # sandbox, the risk argument in channel.py's docstring no longer holds.
    assert NON_PRIMARY_ALLOWED_COMPANIES == ["TUBC"]


# --- dispatch gate ---------------------------------------------------------------------------------


def _sentinel_op(monkeypatch):
    """Register an op that records whether it ran, so 'refused' can be told from 'ran and failed'."""
    calls = []
    monkeypatch.setitem(channel._OPS, "spy_op", lambda company, payload: calls.append(company) or {"ok": 1})
    return calls


@pytest.mark.parametrize("company", ["TUCSH", "UBC", "UCSH"])
def test_a_test_channel_refuses_every_company_but_the_sandbox(monkeypatch, company):
    calls = _sentinel_op(monkeypatch)
    reply = channel._dispatch("spy_op", company, {}, channel_allowed_companies(PR_URL))
    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed_on_channel"
    assert reply["error"]["context"] == {"company": company, "allowed": ["TUBC"]}
    assert calls == []  # refused BEFORE the handler ran - nothing reached GP


def test_a_test_channel_serves_reads_against_the_sandbox(monkeypatch):
    calls = _sentinel_op(monkeypatch)
    reply = channel._dispatch("spy_op", "TUBC", {}, channel_allowed_companies(PR_URL))
    assert reply == {"ok": True, "result": {"ok": 1}}
    assert calls == ["TUBC"]


def test_a_test_channel_also_serves_WRITES_against_the_sandbox(monkeypatch):
    # Deliberate, and the point of the issue: a PR that touches GP has to be verifiable before it
    # merges, so create_* is NOT blacklisted. The company pin is what makes that safe.
    ran = []
    monkeypatch.setitem(channel._OPS, "create_po", lambda company, payload: ran.append(company) or {"po": "PO1"})
    reply = channel._dispatch("create_po", "TUBC", {}, channel_allowed_companies(PR_URL))
    assert reply == {"ok": True, "result": {"po": "PO1"}}
    assert ran == ["TUBC"]


def test_the_production_channel_is_not_restricted_by_this_gate(monkeypatch):
    # None = unrestricted; [gp] allowed_companies alone governs production, exactly as before #414.
    calls = _sentinel_op(monkeypatch)
    reply = channel._dispatch("spy_op", "UCSH", {}, channel_allowed_companies(PRODUCTION_BACKEND_URL))
    assert reply == {"ok": True, "result": {"ok": 1}}
    assert calls == ["UCSH"]


def test_omitting_the_channel_restriction_keeps_the_old_behaviour(monkeypatch):
    calls = _sentinel_op(monkeypatch)
    assert channel._dispatch("spy_op", "UCSH", {})["ok"] is True
    assert calls == ["UCSH"]


def test_an_unknown_op_still_reports_unknown_op_on_a_test_channel():
    # The gate must not swallow the #315 parity signal: a PR that adds an op still needs the relay to
    # answer `unknown_op` so the backend can say "update the relay".
    reply = channel._dispatch("not_a_real_op", "TUBC", {}, channel_allowed_companies(PR_URL))
    assert reply["error"]["error"] == "unknown_op"


def test_a_missing_company_still_reports_missing_company_on_a_test_channel():
    reply = channel._dispatch("list_vendors", "", {}, channel_allowed_companies(PR_URL))
    assert reply["error"]["error"] == "missing_company"


# --- supervisor ------------------------------------------------------------------------------------


def test_run_forever_starts_one_channel_per_configured_url(monkeypatch, tmp_path):
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    asyncio.run(channel.run_forever())
    assert started == [PRODUCTION_BACKEND_URL, PR_URL]


def test_run_forever_is_a_no_op_when_no_backend_is_configured(monkeypatch, tmp_path):
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [])
    asyncio.run(channel.run_forever())
    assert started == []


def test_one_channel_raising_does_not_take_the_others_down(monkeypatch, tmp_path):
    finished: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        if url == PR_URL:
            raise RuntimeError("PR environment went away mid-run")
        await asyncio.sleep(0)
        finished.append(url)

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    asyncio.run(channel.run_forever())  # must not raise
    assert finished == [PRODUCTION_BACKEND_URL]


def test_a_stop_event_reaches_every_channel(monkeypatch, tmp_path):
    seen: list[tuple[str, bool]] = []

    async def fake_run_channel(url, stop_event=None):
        seen.append((url, stop_event is not None and stop_event.is_set()))

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])

    async def run():
        stop = asyncio.Event()
        stop.set()
        await channel.run_forever(stop)

    asyncio.run(run())
    assert seen == [(PRODUCTION_BACKEND_URL, True), (PR_URL, True)]


def _use_backend_urls(monkeypatch, tmp_path, urls: list[str]) -> None:
    """Point get_settings at a config.toml carrying exactly these backend URLs. Writing a real file
    rather than stubbing get_settings keeps the TOML round-trip (which is where a list would break)
    inside the test."""
    rendered = ", ".join(f'"{u}"' for u in urls)
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'[auth]\nshared_secret = "s3cret"\n\n[channel]\nbackend_url = [{rendered}]\n', encoding="utf-8")
    get_settings.cache_clear()
    monkeypatch.setattr(channel, "get_settings", lambda *a, **k: get_settings(str(cfg)))


# --- /health snapshot ------------------------------------------------------------------------------


def test_snapshot_top_level_mirrors_the_production_channel(clean_channel_states):
    # The desktop app's header dot and the update poller read the TOP LEVEL. Neither should start
    # reporting on a throwaway PR-environment channel.
    channel._mark_connected(PRODUCTION_BACKEND_URL)
    channel._mark_disconnected(PR_URL, "secret_rejected")
    snap = channel.channel_state_snapshot()
    assert snap["connected"] is True
    assert snap["state"] == "connected"


def test_snapshot_lists_every_channel_with_its_own_state(clean_channel_states):
    channel._mark_disconnected(PRODUCTION_BACKEND_URL, "disconnected")
    channel._mark_connected(PR_URL)
    channels = channel.channel_state_snapshot()["channels"]
    assert channels == [
        {"url": PRODUCTION_BACKEND_URL, "primary": True, "connected": False, "state": "disconnected"},
        {"url": PR_URL, "primary": False, "connected": True, "state": "connected"},
    ]


def test_snapshot_falls_back_to_the_only_channel_when_none_is_production(clean_channel_states):
    # A dev checkout pointed at localhost has no primary channel; the app must still show its state
    # rather than a permanent 'unknown'.
    channel._mark_connected(PR_URL)
    assert channel.channel_state_snapshot()["state"] == "connected"


def test_snapshot_is_unknown_before_any_channel_runs(clean_channel_states):
    snap = channel.channel_state_snapshot()
    assert snap["connected"] is False
    assert snap["state"] == "unknown"
    assert snap["channels"] == []
