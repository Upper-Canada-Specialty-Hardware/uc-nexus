"""Preview channel discovery: what production tells the workstation relay to dial.

The point of this service is to remove a manual edit on a machine nobody testing is sitting at, so the
failure that matters most is not "wrong list" but "list that quietly stops being served" - a relay that
discovers nothing behaves exactly like the old manual world and nobody notices for a week. These pin
the shape, the filtering, and the fallback behaviour that keeps a Railway blip from tearing down live
channels.

No database and no network: everything here drives the module's own httpx call site.
"""

import pytest

from app.services import relay_channels


@pytest.fixture(autouse=True)
def _reset():
    relay_channels.reset_cache()
    yield
    relay_channels.reset_cache()


@pytest.fixture
def configured(monkeypatch):
    """Discovery switched on, as it is on production alone."""
    monkeypatch.setattr(relay_channels, "RAILWAY_API_TOKEN", "token")
    monkeypatch.setattr(relay_channels, "RAILWAY_PROJECT_ID", "project")


def _envs(*names):
    return {"data": {"environments": {"edges": [{"node": {"id": n, "name": n}} for n in names]}}}


class _Response:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


def _serve(monkeypatch, payload, calls=None):
    def _post(url, **kwargs):
        if calls is not None:
            calls.append(kwargs.get("json", {}).get("query", ""))
        return _Response(payload)

    monkeypatch.setattr(relay_channels.httpx, "post", _post)


def test_only_pr_environments_become_channels(monkeypatch, configured):
    # production and any hand-named environment share the project; neither is a preview backend, and
    # dialling production twice would have the relay fight itself for its single connection slot.
    _serve(monkeypatch, _envs("production", "uc-nexus-pr-554", "staging", "uc-nexus-pr-510"))
    assert relay_channels.discover_preview_channels() == [
        "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link",
        "wss://backend-uc-nexus-pr-510.up.railway.app/relay-link",
    ]


def test_the_newest_pr_is_offered_first(monkeypatch, configured):
    # Ordered by PR number rather than by whatever order Railway returns: the environment somebody is
    # waiting on is almost always the newest one, and the relay logs the list it was handed.
    _serve(monkeypatch, _envs("uc-nexus-pr-9", "uc-nexus-pr-554", "uc-nexus-pr-77"))
    assert relay_channels.discover_preview_channels() == [
        "wss://backend-uc-nexus-pr-554.up.railway.app/relay-link",
        "wss://backend-uc-nexus-pr-77.up.railway.app/relay-link",
        "wss://backend-uc-nexus-pr-9.up.railway.app/relay-link",
    ]


@pytest.mark.parametrize(
    "name",
    [
        "pr-554",  # the shape the runbook warns about; Railway does not name environments this way
        "uc-nexus-pr-554-old",
        "not-uc-nexus-pr-554",
        "uc-nexus-pr-",
        "uc-nexus-pr-abc",
    ],
)
def test_a_name_that_is_not_exactly_a_pr_environment_is_ignored(monkeypatch, configured, name):
    # The name is the ONLY thing standing between "an environment exists" and "the relay dials it".
    _serve(monkeypatch, _envs(name))
    assert relay_channels.discover_preview_channels() == []


def test_discovery_is_off_without_a_token(monkeypatch):
    monkeypatch.setattr(relay_channels, "RAILWAY_API_TOKEN", "")
    monkeypatch.setattr(relay_channels, "RAILWAY_PROJECT_ID", "project")

    def _explode(*a, **k):  # pragma: no cover - must never run
        raise AssertionError("a backend without a token must not call Railway")

    monkeypatch.setattr(relay_channels.httpx, "post", _explode)
    assert relay_channels.discover_preview_channels() == []


def test_a_railway_outage_keeps_the_last_good_answer(monkeypatch, configured):
    # The relay retires a channel that stops being listed, so answering [] on a blip would tear down
    # working preview channels and re-create them a minute later.
    _serve(monkeypatch, _envs("uc-nexus-pr-554"))
    good = relay_channels.discover_preview_channels()
    assert good == ["wss://backend-uc-nexus-pr-554.up.railway.app/relay-link"]

    def _fail(*a, **k):
        raise RuntimeError("connection reset")

    monkeypatch.setattr(relay_channels.httpx, "post", _fail)
    assert relay_channels.discover_preview_channels(force=True) == good


def test_no_live_previews_really_does_answer_empty(monkeypatch, configured):
    # The other half of the rule above: "asked and there are none" must be distinguishable from
    # "could not ask", or a closed PR's environment is dialled forever.
    _serve(monkeypatch, _envs("production"))
    assert relay_channels.discover_preview_channels() == []


def test_the_fallback_query_runs_only_when_the_first_is_refused(monkeypatch, configured):
    calls: list[str] = []

    def _post(url, **kwargs):
        query = kwargs.get("json", {}).get("query", "")
        calls.append(query)
        if "project(id:" not in query:
            return _Response({"errors": [{"message": "Cannot query field 'environments'"}]})
        return _Response({"data": {"project": {"environments": {"edges": [{"node": {"name": "uc-nexus-pr-1"}}]}}}})

    monkeypatch.setattr(relay_channels.httpx, "post", _post)
    assert relay_channels.discover_preview_channels() == [
        "wss://backend-uc-nexus-pr-1.up.railway.app/relay-link",
    ]
    assert len(calls) == 2


def test_a_shape_nobody_expected_is_an_empty_list_not_a_crash(monkeypatch, configured):
    # This walks a third party's response on a request path; a surprise there must not 500 the route.
    _serve(monkeypatch, {"data": {"environments": None}})
    assert relay_channels.discover_preview_channels() == []


def test_a_refusal_names_the_reason_in_the_message_itself(monkeypatch, configured, caplog):
    # The whole value of this warning is that somebody reads it in a Railway deploy log and knows what
    # to change. The first version put Railway's errors in the log record's `extra`, which the stdlib's
    # default formatter drops - so the line arrived saying only "refused both queries" and cost a
    # deploy cycle to learn nothing. The reason has to be IN the message.
    _serve(monkeypatch, {"errors": [{"message": "Not Authorized"}]})
    with caplog.at_level("WARNING"):
        assert relay_channels.discover_preview_channels() == []
    rendered = caplog.records[-1].getMessage()
    assert "Not Authorized" in rendered
    assert "project" in rendered


def test_an_unreachable_api_names_the_reason_too(monkeypatch, configured, caplog):
    def _fail(*a, **k):
        raise RuntimeError("getaddrinfo failed")

    monkeypatch.setattr(relay_channels.httpx, "post", _fail)
    with caplog.at_level("WARNING"):
        assert relay_channels.discover_preview_channels() == []
    assert "getaddrinfo failed" in caplog.records[-1].getMessage()


def test_a_failing_api_is_not_called_on_every_relay_tick(monkeypatch, configured):
    # Only a SUCCESS refreshes the cache, so without a separate floor on attempts the relay's ten
    # second reconcile turns into a Railway call every ten seconds. Watched a relay with a stale
    # secret produce 42 rejected calls in minutes; the rate limit is hourly and shared.
    calls: list[str] = []

    def _fail(url, **kwargs):
        calls.append(url)
        raise RuntimeError("connection reset")

    monkeypatch.setattr(relay_channels.httpx, "post", _fail)
    for _ in range(6):
        assert relay_channels.discover_preview_channels() == []
    assert len(calls) == 1


def test_the_floor_does_not_outlast_a_recovery(monkeypatch, configured):
    # It has to be well under the success cache life, or a recovered API stays unnoticed for a minute.
    assert relay_channels._FAILURE_RETRY_SECONDS < relay_channels._CACHE_SECONDS


def test_the_answer_is_cached_between_relay_ticks(monkeypatch, configured):
    calls: list[str] = []
    _serve(monkeypatch, _envs("uc-nexus-pr-554"), calls=calls)
    for _ in range(5):
        relay_channels.discover_preview_channels()
    assert len(calls) == 1
