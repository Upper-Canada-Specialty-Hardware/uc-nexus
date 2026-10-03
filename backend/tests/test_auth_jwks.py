"""#1330: fetching Clerk's key set must not stall every request.

The key set is fetched synchronously inside the per-field guard, which runs on the event loop. Before
this, a token with an unknown key id forced a refetch on every request, a Clerk outage was retried by
every root field of every query, and the httpx error reached the browser as a masked INTERNAL rather
than a sign-in problem. No database: httpx is replaced and the module's caches are reset per test.
"""

import json

import httpx
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

from app import auth
from app.errors import AppError


def _jwk(kid: str) -> dict:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048).public_key()
    return {**json.loads(RSAAlgorithm.to_jwk(key)), "kid": kid, "use": "sig", "alg": "RS256"}


_KEY_SET = {"keys": [_jwk("k1")]}


class _Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


@pytest.fixture
def clock(monkeypatch):
    c = _Clock()
    monkeypatch.setattr(auth.time, "monotonic", c)
    return c


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    monkeypatch.setattr(auth, "CLERK_SECRET_KEY", "sk_test")
    monkeypatch.setattr(auth, "_jwks_cache", {"data": None, "fetched_at": 0.0})
    monkeypatch.setattr(auth, "_jwks_state", {"forced_at": 0.0, "failed_at": None, "refreshing": False})
    monkeypatch.setattr(auth, "_kid_misses", {})


@pytest.fixture
def fetches(monkeypatch):
    """Count httpx.get calls; each answers with whatever `fetches.reply` is (a dict or an exception)."""

    class Recorder:
        count = 0
        reply: object = _KEY_SET

    def fake_get(url, headers=None, timeout=None):
        Recorder.count += 1
        if isinstance(Recorder.reply, Exception):
            raise Recorder.reply
        request = httpx.Request("GET", url)
        return httpx.Response(200, json=Recorder.reply, request=request)

    monkeypatch.setattr(auth.httpx, "get", fake_get)

    # The routine stale refresh runs in a thread; run it inline so the count is deterministic.
    def refresh_inline() -> None:
        try:
            auth._fetch_jwks()
        except auth.AuthError:
            pass  # as the background thread does: the stale set keeps serving

    monkeypatch.setattr(auth, "_refresh_in_background", refresh_inline)
    return Recorder


def _assert_unauthenticated(exc_info):
    assert isinstance(exc_info.value, auth.AuthError)
    assert isinstance(exc_info.value, AppError)
    assert exc_info.value.code == "UNAUTHENTICATED"


def test_an_unknown_key_id_costs_one_refetch_then_is_refused_from_memory(clock, fetches):
    with pytest.raises(auth.AuthError) as first:
        auth._signing_key("bogus")
    _assert_unauthenticated(first)
    assert fetches.count == 2  # the cold load, then the one forced refetch for the miss

    for _ in range(20):
        with pytest.raises(auth.AuthError):
            auth._signing_key("bogus")
    assert fetches.count == 2


def test_forced_refetches_are_limited_to_one_a_minute_across_different_unknown_kids(clock, fetches):
    with pytest.raises(auth.AuthError):
        auth._signing_key("bogus-1")
    assert fetches.count == 2

    clock.now += 5
    for i in range(2, 12):
        with pytest.raises(auth.AuthError):
            auth._signing_key(f"bogus-{i}")
    assert fetches.count == 2

    clock.now += auth._JWKS_FORCE_MIN_INTERVAL_SECONDS
    with pytest.raises(auth.AuthError):
        auth._signing_key("bogus-late")
    assert fetches.count == 3


def test_a_rotated_key_is_found_by_the_forced_refetch(clock, fetches):
    auth._load_jwks()
    assert fetches.count == 1
    clock.now += auth._JWKS_FORCE_MIN_INTERVAL_SECONDS
    rotated = {"keys": [*_KEY_SET["keys"], _jwk("k2")]}
    fetches.reply = rotated

    assert auth._signing_key("k2") is not None
    assert fetches.count == 2


def test_a_clerk_outage_is_an_unauthenticated_refusal_not_an_internal_error(clock, fetches):
    fetches.reply = httpx.ConnectError("clerk is down")

    with pytest.raises(auth.AuthError) as exc:
        auth._load_jwks()
    _assert_unauthenticated(exc)
    assert exc.value.message == "Could not verify sign-in right now"


def test_after_a_failed_fetch_requests_are_refused_without_another_stall(clock, fetches):
    fetches.reply = httpx.ConnectError("clerk is down")
    with pytest.raises(auth.AuthError):
        auth._load_jwks()
    assert fetches.count == 1

    for _ in range(10):
        with pytest.raises(auth.AuthError):
            auth._load_jwks()
    assert fetches.count == 1

    clock.now += auth._JWKS_FAILURE_BACKOFF_SECONDS
    fetches.reply = _KEY_SET
    assert auth._load_jwks() == _KEY_SET
    assert fetches.count == 2


def test_a_bad_response_body_is_an_unauthenticated_refusal(clock, fetches):
    fetches.reply = ["not", "a", "key", "set"]

    with pytest.raises(auth.AuthError) as exc:
        auth._load_jwks()
    _assert_unauthenticated(exc)


def test_a_stale_set_is_served_while_it_refreshes(clock, fetches):
    auth._load_jwks()
    clock.now += auth._JWKS_TTL_SECONDS + 1
    fetches.reply = httpx.ConnectError("clerk is down")

    # The refresh fails, but the request is answered from the stale set rather than refused.
    assert auth._load_jwks() == _KEY_SET
    assert fetches.count == 2


def test_a_failed_fetch_is_memoised_for_the_whole_request(clock, fetches, monkeypatch):
    fetches.reply = httpx.ConnectError("clerk is down")

    class _Request:
        headers = {"authorization": "Bearer header.payload.sig"}

    monkeypatch.setattr(auth.jwt, "get_unverified_header", lambda token: {"kid": "k1"})
    context = {"request": _Request()}
    for _ in range(8):  # eight root fields of one query
        with pytest.raises(auth.AuthError):
            auth.authenticated_user_id(context)
    assert fetches.count == 1
