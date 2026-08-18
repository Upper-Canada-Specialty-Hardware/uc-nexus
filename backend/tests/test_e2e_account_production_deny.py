"""The dedicated e2e account is refused on production, at the identity chokepoint.

GET /testing/session mints a session for E2E_CLERK_USER_ID and the link lives in a public PR comment;
every environment shares the one production Clerk instance, so that ticket is a valid PRODUCTION JWT.
The deny pinned here is what makes the link safe to hand around - without it, repo read plus a leaked
key would be a staff-level session on production. Same shape as test_testing_sign_in_secret.py: the
load-bearing assertions are the ones proving the refusal fires on production and stays inert
everywhere else.

Nothing here hits api.clerk.com - the two chokepoint tests fake the JWT verify so a "verified" e2e
subject can be fed in without a network call.
"""

import pytest

from app import auth, config
from app.auth import ForbiddenError

_E2E_USER = "user_e2e_tester"


class _RequestWithBearer:
    """Minimal stand-in for a FastAPI Request carrying a bearer header - enough for _bearer_token."""

    def __init__(self, token: str):
        self.headers = {"authorization": f"Bearer {token}"}


@pytest.fixture(autouse=True)
def _clear(monkeypatch):
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", "")
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "")


def _prod(monkeypatch):
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "production")


def test_the_e2e_account_is_refused_on_production(monkeypatch):
    # THE test in this file: a ticket minted for this account must be dead on production.
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", _E2E_USER)
    _prod(monkeypatch)
    with pytest.raises(ForbiddenError):
        auth._reject_e2e_account_in_production(_E2E_USER)


@pytest.mark.parametrize("name", ["Production", "PRODUCTION", "  production  "])
def test_production_is_recognised_however_cased_or_padded(monkeypatch, name):
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", _E2E_USER)
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", name)
    with pytest.raises(ForbiddenError):
        auth._reject_e2e_account_in_production(_E2E_USER)


def test_the_account_is_allowed_on_a_preview_environment(monkeypatch):
    # The whole point: a first-class account everywhere BUT production.
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", _E2E_USER)
    monkeypatch.setattr(config, "RAILWAY_ENVIRONMENT_NAME", "uc-nexus-pr-999")
    auth._reject_e2e_account_in_production(_E2E_USER)  # no raise


def test_a_real_account_is_never_touched_on_production(monkeypatch):
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", _E2E_USER)
    _prod(monkeypatch)
    auth._reject_e2e_account_in_production("user_a_real_person")  # no raise


def test_inert_when_no_e2e_account_is_configured(monkeypatch):
    # A blank id must never match a caller (nor a blank-ish subject) - fail inert, not open.
    _prod(monkeypatch)
    auth._reject_e2e_account_in_production(_E2E_USER)  # no raise
    auth._reject_e2e_account_in_production("")  # no raise


def test_the_deny_fires_through_authenticated_user_id_on_production(monkeypatch):
    """The chokepoint every gated GraphQL field funnels through. A verified e2e subject is refused
    before any resolver runs, and the refusal is memoised as itself rather than swallowed into an
    identity."""
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", _E2E_USER)
    _prod(monkeypatch)
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": _E2E_USER})

    context = {"request": _RequestWithBearer("any-token")}
    with pytest.raises(ForbiddenError):
        auth.authenticated_user_id(context)
    with pytest.raises(ForbiddenError):
        auth.authenticated_user_id(context)


def test_the_deny_fires_through_require_admin_request_on_production(monkeypatch):
    """The plain-route gate (/admin/reset-data, /testing/clerk-sign-in). The refusal lands before the
    Clerk roles lookup, so no roster call is needed to reach it."""
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", _E2E_USER)
    _prod(monkeypatch)
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": _E2E_USER})

    with pytest.raises(ForbiddenError):
        auth.require_admin_request(_RequestWithBearer("any-token"))
