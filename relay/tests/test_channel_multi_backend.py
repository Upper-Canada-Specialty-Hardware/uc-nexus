"""Multi-backend channels (issue #414).

A Railway PR environment can only exercise a relay-dependent path if a relay dials it, and the relay
used to have exactly one backend URL - so verifying a GP-touching change meant re-pointing the
workstation, which un-pairs it from production. These cover the two halves of the fix: one channel per
configured URL, and a hard company pin on every channel that is not production.

The company pin is the load-bearing part. Test channels serve reads AND writes on purpose, so the only
thing standing between a PR environment and a live GP company is `_dispatch` refusing it.
"""

import asyncio
import contextlib
import json
import logging
from pathlib import Path

import pytest

from ucnexus_relay import channel
from ucnexus_relay.config import (
    NON_PRIMARY_ALLOWED_COMPANIES,
    PRODUCTION_BACKEND_URL,
    ChannelCfg,
    channel_allowed_companies,
    get_settings,
    is_primary_backend_url,
    primary_url,
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


def test_the_sandbox_pin_is_sandboxes_only():
    # The whole reason a test channel may write to GP at all. If this list ever grows past the
    # sandboxes, the risk argument in channel.py's docstring no longer holds - so it is pinned here
    # rather than left to whatever someone edits it to.
    assert NON_PRIMARY_ALLOWED_COMPANIES == ["TUBC", "TUCSH"]
    assert not {"UBC", "UCSH"} & set(NON_PRIMARY_ALLOWED_COMPANIES)


# --- dispatch gate ---------------------------------------------------------------------------------


def _sentinel_op(monkeypatch):
    """Register an op that records whether it ran, so 'refused' can be told from 'ran and failed'."""
    calls = []
    monkeypatch.setitem(channel._OPS, "spy_op", lambda company, payload: calls.append(company) or {"ok": 1})
    return calls


@pytest.mark.parametrize("company", ["UBC", "UCSH", "TUCA"])
def test_a_test_channel_refuses_every_company_but_the_sandboxes(monkeypatch, company):
    calls = _sentinel_op(monkeypatch)
    reply = channel._dispatch("spy_op", company, {}, channel_allowed_companies(PR_URL))
    assert reply["ok"] is False
    assert reply["error"]["error"] == "company_not_allowed_on_channel"
    assert reply["error"]["context"] == {"company": company, "allowed": ["TUBC", "TUCSH"]}
    assert calls == []  # refused BEFORE the handler ran - nothing reached GP


@pytest.mark.parametrize("company", ["TUBC", "TUCSH"])
def test_a_test_channel_serves_reads_against_the_sandboxes(monkeypatch, company):
    calls = _sentinel_op(monkeypatch)
    reply = channel._dispatch("spy_op", company, {}, channel_allowed_companies(PR_URL))
    assert reply == {"ok": True, "result": {"ok": 1}}
    assert calls == [company]


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
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    asyncio.run(_supervise_for_one_tick(monkeypatch))
    assert started == [PRODUCTION_BACKEND_URL, PR_URL]


def test_run_forever_starts_nothing_when_no_backend_is_configured(monkeypatch, tmp_path):
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [])
    asyncio.run(_supervise_for_one_tick(monkeypatch))
    assert started == []


def test_one_channel_raising_does_not_take_the_others_down(monkeypatch, tmp_path):
    finished: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        if url == PR_URL:
            raise RuntimeError("PR environment went away mid-run")
        await asyncio.sleep(0)
        finished.append(url)
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    asyncio.run(_supervise_for_one_tick(monkeypatch))  # must not raise
    assert finished == [PRODUCTION_BACKEND_URL]


def test_a_stop_event_reaches_every_channel(monkeypatch, tmp_path):
    seen: list[tuple[str, bool]] = []

    async def fake_run_channel(url, stop_event=None):
        seen.append((url, stop_event is not None))
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    asyncio.run(_supervise_for_one_tick(monkeypatch))
    assert seen == [(PRODUCTION_BACKEND_URL, True), (PR_URL, True)]


# --- reconcile (#456) -------------------------------------------------------------------------------
# The supervisor keeps its channel set in step with config.toml, so adding or removing a Railway
# preview environment takes effect on its own. What used to be needed instead was a click on the
# desktop app's Restart Relay button, which an agent editing config.toml cannot do - and on an empty
# preview database nothing is testable until the channel is up, because the project list itself comes
# from GP.


def test_a_url_added_to_config_gets_a_channel_without_a_restart(monkeypatch, tmp_path):
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    cfg = _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        await _tick()
        assert started == [PRODUCTION_BACKEND_URL]  # the PR environment is not in config.toml yet

        _write_backend_urls(cfg, [PRODUCTION_BACKEND_URL, PR_URL])
        await _tick()
        await _stop(stop, task)

    asyncio.run(run())
    assert started == [PRODUCTION_BACKEND_URL, PR_URL]
    # And production was never dropped to pick the new one up - it is still the same one channel.
    assert started.count(PRODUCTION_BACKEND_URL) == 1


def test_a_url_removed_from_config_has_its_channel_cancelled(monkeypatch, tmp_path, clean_channel_states):
    """A closed PR's environment is torn down, and its URL then retries forever against a backend
    that no longer exists. Removing the line has to be enough to stop it."""
    cancelled: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        try:
            await _forever()
        except asyncio.CancelledError:
            cancelled.append(url)
            raise

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    cfg = _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        await _tick()
        assert PR_URL in channel._STATES

        _write_backend_urls(cfg, [PRODUCTION_BACKEND_URL])
        await _tick()
        # Read the state HERE, before shutting the supervisor down: shutting down cancels every
        # remaining channel, which would make production look retired too.
        observed = (list(cancelled), dict(channel._STATES))
        await _stop(stop, task)
        return observed

    cancelled_by_reconcile, states = asyncio.run(run())
    assert cancelled_by_reconcile == [PR_URL]
    # Its /health row goes with it, or the desktop app keeps listing a backend nobody is dialling.
    assert PR_URL not in states
    assert PRODUCTION_BACKEND_URL in states


def test_a_config_that_will_not_parse_leaves_the_running_channels_alone(
    monkeypatch, tmp_path, clean_channel_states
):
    """Hand-editing config.toml on a running relay is the documented way to add a test backend, so a
    save caught mid-write is a live possibility. It must not take production's channel down - there
    would then be no way back without the restart this whole change exists to remove."""
    cancelled: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        try:
            await _forever()
        except asyncio.CancelledError:
            cancelled.append(url)
            raise

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    cfg = _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        await _tick()

        cfg.write_text('[channel]\nbackend_url = ["wss://half-writ', encoding="utf-8")
        await _tick()
        survived_the_bad_parse = list(cancelled)

        _write_backend_urls(cfg, [PRODUCTION_BACKEND_URL, PR_URL])
        await _tick()
        observed = (survived_the_bad_parse, dict(channel._STATES))
        await _stop(stop, task)
        return observed

    cancelled_by_reconcile, states = asyncio.run(run())
    assert cancelled_by_reconcile == []  # still up, still dialling production
    # And the finished edit is picked up once it parses, so a mid-write save costs one interval and
    # not the channel.
    assert PR_URL in states


# --- re-enrolment (the secret changing under a live channel) ----------------------------------------
# _run_channel re-reads the secret before every dial, so a channel that is DOWN heals itself. A
# CONNECTED one holds a socket authenticated with the old secret and would never dial again to find
# out - which reads as "enrolled fine, still not working" and used to need a serve restart.


def test_a_re_enrolment_restarts_the_running_channels(monkeypatch, tmp_path, caplog, clean_channel_states):
    started: list[str] = []
    cancelled: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        try:
            await _forever()
        except asyncio.CancelledError:
            cancelled.append(url)
            raise

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    cfg = _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        await _tick()
        assert started == [PRODUCTION_BACKEND_URL]

        _write_backend_urls(cfg, [PRODUCTION_BACKEND_URL], secret="re-enrolled")
        await _tick()
        observed = (list(started), list(cancelled))
        await _stop(stop, task)
        return observed

    with caplog.at_level(logging.WARNING):
        started_urls, cancelled_urls = asyncio.run(run())
    assert cancelled_urls == [PRODUCTION_BACKEND_URL]
    assert started_urls == [PRODUCTION_BACKEND_URL, PRODUCTION_BACKEND_URL]  # torn down, then re-dialled
    assert any(getattr(r, "category", None) == "secret_changed" for r in caplog.records)


def test_a_removed_url_is_retired_rather_than_restarted_when_the_secret_also_changed(
    monkeypatch, tmp_path, clean_channel_states
):
    # One edit can do both (re-enrol and drop a PR URL). Restarting the channel that is on its way out
    # would leave its /health row behind, listing a backend nobody is dialling.
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    cfg = _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        await _tick()
        _write_backend_urls(cfg, [PRODUCTION_BACKEND_URL], secret="re-enrolled")
        # The restart and the retirement each await their own cancellation, so this reconcile takes
        # more turns of the loop than a plain one.
        await _tick()
        await _tick()
        observed = (list(started), dict(channel._STATES))
        await _stop(stop, task)
        return observed

    started_urls, states = asyncio.run(run())
    assert started_urls.count(PR_URL) == 1  # never re-dialled
    assert PR_URL not in states  # and its row went with it
    assert PRODUCTION_BACKEND_URL in states


def test_an_unchanged_secret_leaves_the_channels_alone(monkeypatch, tmp_path, clean_channel_states):
    # The supervisor re-reads config.toml every few seconds; restarting on each read would drop the
    # backend connection continuously.
    started: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        started.append(url)
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        for _ in range(5):
            await _tick()
        await _stop(stop, task)

    asyncio.run(run())
    assert started == [PRODUCTION_BACKEND_URL, PR_URL]


def test_a_config_that_will_not_parse_never_reads_as_a_changed_secret(monkeypatch, tmp_path, clean_channel_states):
    # A save caught mid-write has no readable secret at all, and treating that as "it changed" would
    # bounce production's channel every time somebody edits the file.
    cancelled: list[str] = []

    async def fake_run_channel(url, stop_event=None):
        try:
            await _forever()
        except asyncio.CancelledError:
            cancelled.append(url)
            raise

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    cfg = _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        await _tick()
        cfg.write_text('[channel]\nbackend_url = ["wss://half-writ', encoding="utf-8")
        await _tick()
        observed = list(cancelled)
        await _stop(stop, task)
        return observed

    assert asyncio.run(run()) == []


async def _forever() -> None:
    """Stand in for a healthy channel: _run_channel never returns on its own."""
    await asyncio.Event().wait()


async def _tick() -> None:
    """Let the supervisor run one reconcile pass. The interval is patched to 0, so yielding to the
    loop a few times is enough for it to come round again and for the tasks it spawns to start."""
    for _ in range(6):
        await asyncio.sleep(0)


def _start_supervisor(monkeypatch) -> tuple[asyncio.Event, asyncio.Task]:
    monkeypatch.setattr(channel, "CHANNEL_RECONCILE_SECONDS", 0)
    stop = asyncio.Event()
    return stop, asyncio.create_task(channel.run_forever(stop))


async def _stop(stop: asyncio.Event, task: asyncio.Task) -> None:
    stop.set()
    await _tick()
    task.cancel()
    with contextlib.suppress(asyncio.CancelledError):
        await task


async def _supervise_for_one_tick(monkeypatch) -> None:
    stop, task = _start_supervisor(monkeypatch)
    await _tick()
    await _stop(stop, task)


def _write_backend_urls(cfg: Path, urls: list[str], secret: str = "s3cret") -> None:
    rendered = ", ".join(f'"{u}"' for u in urls)
    cfg.write_text(
        f'[auth]\nshared_secret = "{secret}"\n\n[channel]\nbackend_url = [{rendered}]\n', encoding="utf-8"
    )


def _use_backend_urls(monkeypatch, tmp_path, urls: list[str]) -> Path:
    """Point get_settings at a config.toml carrying exactly these backend URLs. Writing a real file
    rather than stubbing get_settings keeps the TOML round-trip (which is where a list would break)
    inside the test - and since #456 it is also what lets a test EDIT the file under a running
    supervisor, which is the whole behaviour being checked.

    The stub carries `cache_clear` because the supervisor drops the lru_cache before every read, for
    exactly the reason these tests rely on: without it a re-read returns the file as it was the first
    time it was parsed."""
    cfg = tmp_path / "config.toml"
    _write_backend_urls(cfg, urls)
    get_settings.cache_clear()

    def stub(*a, **k):
        return get_settings(str(cfg))

    stub.cache_clear = get_settings.cache_clear
    monkeypatch.setattr(channel, "get_settings", stub)
    return cfg


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


# --- the URL -> dispatch wiring (the pin is only as good as the thing that supplies it) -------------


class _FakeWs:
    """Just enough of a websockets client for _run_once: an async iterator of raw frames, plus send."""

    def __init__(self, jobs, done):
        self._jobs, self._done, self.sent = list(jobs), done, []

    async def send(self, payload):
        self.sent.append(json.loads(payload))

    def __aiter__(self):
        async def gen():
            for job in self._jobs:
                yield json.dumps(job)
            # Hold the read loop open until the job has actually been dispatched, otherwise _run_once's
            # finally cancels the in-flight task and the assertion races.
            await self._done.wait()

        return gen()


def _fake_connect(monkeypatch, ws):
    class _Cm:
        async def __aenter__(self):
            return ws

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(channel.websockets, "connect", lambda url, **kw: _Cm())


def _capture_allowed(monkeypatch, done):
    """Record the allowed_companies that _run_once threads into _handle_job."""
    seen = []

    async def fake_handle_job(job, allowed_companies=None):
        seen.append(allowed_companies)
        done.set()
        return {"id": job.get("id"), "ok": True, "result": {}}

    monkeypatch.setattr(channel, "_handle_job", fake_handle_job)
    return seen


def test_run_once_threads_the_sandbox_pin_into_dispatch_on_a_test_channel(monkeypatch, clean_channel_states):
    # The gate itself is well covered above, but it is a DEFAULTED parameter whose default is
    # "unrestricted" - so the thing actually worth pinning down is that _run_once supplies it. Without
    # this, deleting the argument at the _handle_job call site would still pass CI while handing every
    # test backend full production-company access.
    async def run():
        done = asyncio.Event()
        seen = _capture_allowed(monkeypatch, done)
        ws = _FakeWs([{"id": "j1", "op": "list_vendors", "company": "TUBC", "payload": {}}], done)
        _fake_connect(monkeypatch, ws)
        await channel._run_once(PR_URL, "secret", channel.get_settings().channel)
        return seen

    assert asyncio.run(run()) == [NON_PRIMARY_ALLOWED_COMPANIES]


def test_run_once_leaves_the_production_channel_unrestricted(monkeypatch, clean_channel_states):
    async def run():
        done = asyncio.Event()
        seen = _capture_allowed(monkeypatch, done)
        ws = _FakeWs([{"id": "j1", "op": "list_vendors", "company": "UCSH", "payload": {}}], done)
        _fake_connect(monkeypatch, ws)
        await channel._run_once(PRODUCTION_BACKEND_URL, "secret", channel.get_settings().channel)
        return seen

    assert asyncio.run(run()) == [None]


# --- extra_backend_urls: adding a test backend without retyping production -------------------------


def test_extra_backend_urls_appends_to_the_baked_production_default():
    # The whole point: the operator names ONLY the new backend, so a typo cannot silently demote
    # production to a restricted channel (there is nothing to mistype about production's URL).
    cfg = ChannelCfg(extra_backend_urls=[PR_URL])
    assert cfg.backend_urls == [PRODUCTION_BACKEND_URL, PR_URL]
    assert [is_primary_backend_url(u) for u in cfg.backend_urls] == [True, False]


def test_extra_backend_urls_listing_production_again_is_harmless():
    cfg = ChannelCfg(extra_backend_urls=[PRODUCTION_BACKEND_URL, PR_URL])
    assert cfg.backend_urls == [PRODUCTION_BACKEND_URL, PR_URL]


def test_extra_backend_urls_defaults_to_nothing_extra():
    assert ChannelCfg().backend_urls == [PRODUCTION_BACKEND_URL]


def test_a_blank_backend_url_with_extras_still_yields_only_the_extras():
    assert ChannelCfg(backend_url="", extra_backend_urls=[PR_URL]).backend_urls == [PR_URL]


def test_primary_url_is_the_single_definition_of_which_channel_is_production():
    assert primary_url([PR_URL, PRODUCTION_BACKEND_URL]) == PRODUCTION_BACKEND_URL
    assert primary_url([PR_URL]) == PR_URL  # dev checkout: fall back rather than show nothing
    assert primary_url([]) == ""


# --- operator-error signalling ----------------------------------------------------------------------


def test_run_forever_warns_when_no_channel_is_production(monkeypatch, tmp_path, caplog):
    # The failure this catches: a hand-typed backend_url list with a wrong character in production's
    # URL. Every channel is then sandbox-pinned and all real GP work is refused, which is otherwise
    # visible only as an INFO field.
    async def fake_run_channel(url, stop_event=None):
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PR_URL])
    with caplog.at_level(logging.WARNING):
        asyncio.run(_supervise_for_one_tick(monkeypatch))
    assert any("no production channel configured" in r.message for r in caplog.records)


def test_run_forever_is_quiet_when_production_is_present(monkeypatch, tmp_path, caplog):
    async def fake_run_channel(url, stop_event=None):
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    with caplog.at_level(logging.WARNING):
        asyncio.run(_supervise_for_one_tick(monkeypatch))
    assert not any("no production channel configured" in r.message for r in caplog.records)


def test_the_no_production_warning_is_not_repeated_on_every_tick(monkeypatch, tmp_path, caplog):
    """The supervisor re-reads config.toml every few seconds since #456. A warning that fired on each
    pass would bury relay.log within a day, so it is tied to the URL SET changing, not to the read."""

    async def fake_run_channel(url, stop_event=None):
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PR_URL])

    async def run():
        stop, task = _start_supervisor(monkeypatch)
        for _ in range(5):
            await _tick()
        await _stop(stop, task)

    with caplog.at_level(logging.WARNING):
        asyncio.run(run())
    assert len([r for r in caplog.records if "no production channel configured" in r.message]) == 1


def test_a_channel_that_escapes_its_retry_loop_is_logged_and_marked_failed(monkeypatch, tmp_path, caplog):
    # Nothing awaits these tasks while they are healthy, so the log has to come from the per-channel
    # wrapper or a dead channel is invisible.
    async def fake_run_channel(url, stop_event=None):
        if url == PR_URL:
            raise RuntimeError("boom")
        await _forever()

    monkeypatch.setattr(channel, "_run_channel", fake_run_channel)
    _use_backend_urls(monkeypatch, tmp_path, [PRODUCTION_BACKEND_URL, PR_URL])
    with caplog.at_level(logging.ERROR):
        asyncio.run(_supervise_for_one_tick(monkeypatch))
    assert any("exited unexpectedly" in r.message for r in caplog.records)
    assert channel._STATES[PR_URL]["state"] == "failed"


def test_register_channels_lists_every_channel_before_any_of_them_dials(clean_channel_states):
    # So an operator who just added a PR URL sees it on the status panel immediately, rather than only
    # after its first connection attempt.
    channel.register_channels([PRODUCTION_BACKEND_URL, PR_URL])
    channels = channel.channel_state_snapshot()["channels"]
    assert [c["url"] for c in channels] == [PRODUCTION_BACKEND_URL, PR_URL]
    assert all(c["connected"] is False and c["state"] == "unknown" for c in channels)


def test_register_channels_does_not_clobber_a_live_state(clean_channel_states):
    channel._mark_connected(PRODUCTION_BACKEND_URL)
    channel.register_channels([PRODUCTION_BACKEND_URL, PR_URL])
    assert channel._STATES[PRODUCTION_BACKEND_URL]["state"] == "connected"


def test_the_refusal_message_reads_as_prose_not_a_python_list():
    # relay_gateway surfaces error["message"] as the GraphQL error the browser shows.
    reply = channel._dispatch("list_vendors", "UCSH", {}, ["TUBC"])
    assert "['TUBC']" not in reply["error"]["message"]
    assert "only TUBC is" in reply["error"]["message"]


def test_the_refusal_message_reads_as_a_sentence_with_two_sandboxes():
    # The sandbox pin is a list, and "only TUBC, TUCSH is" is what a plain join produces - in the
    # browser, on the error the user actually sees.
    reply = channel._dispatch("list_vendors", "UCSH", {}, NON_PRIMARY_ALLOWED_COMPANIES)
    assert "only TUBC and TUCSH are" in reply["error"]["message"]
