"""A Clerk failure on a save or the roster read says Clerk, not the server (#1934).

The single-user reads already mapped an httpx failure to CLERK_UNAVAILABLE; the roster (behind the users
page and the shipping driver check) and the writes (roles, buyer identity, company, demo mode, name) did a
raw `raise_for_status`, so Clerk being down or refusing a value was the masked "something went wrong".
"""

import httpx
import pytest

from app.errors import AppError, ValidationError
from app.repositories import user_repository


class _FakeClerk:
    """Stands in for the httpx client: every call answers `status` with `body`, or raises `error`."""

    def __init__(self, *, status: int = 200, body=None, error: Exception | None = None):
        self.status = status
        self.body = body
        self.error = error

    def _answer(self, method: str, path: str):
        if self.error is not None:
            raise self.error
        request = httpx.Request(method, f"https://clerk.test{path}")
        return httpx.Response(self.status, json=self.body, request=request)

    def get(self, path, headers=None, params=None):
        return self._answer("GET", path)

    def patch(self, path, headers=None, json=None):
        return self._answer("PATCH", path)


@pytest.fixture
def clerk(monkeypatch):
    def _make(**kw):
        fake = _FakeClerk(**kw)
        monkeypatch.setattr(user_repository, "_client", fake)
        monkeypatch.setattr(user_repository, "_headers", lambda: {})
        return fake

    return _make


def test_the_roster_read_failing_is_clerk_unavailable(clerk):
    clerk(error=httpx.ConnectError("down"))
    with pytest.raises(AppError) as e:
        user_repository.list_users()
    assert e.value.code == "CLERK_UNAVAILABLE"


def test_the_roster_read_answering_5xx_is_clerk_unavailable(clerk):
    clerk(status=503, body={"errors": [{"message": "unavailable"}]})
    with pytest.raises(AppError) as e:
        user_repository.list_users()
    assert e.value.code == "CLERK_UNAVAILABLE"


@pytest.mark.parametrize(
    "save",
    [
        lambda: user_repository.update_user_name("u_1", "Mira", "Lane"),
        lambda: user_repository.update_user_demo_mode("u_1", True),
    ],
    ids=["name", "metadata"],
)
def test_a_save_clerk_cannot_take_is_clerk_unavailable(clerk, save):
    clerk(error=httpx.ReadTimeout("slow"))
    with pytest.raises(AppError) as e:
        save()
    assert e.value.code == "CLERK_UNAVAILABLE"

    clerk(status=500, body={})
    with pytest.raises(AppError) as e:
        save()
    assert e.value.code == "CLERK_UNAVAILABLE"


def test_a_value_clerk_refuses_reads_in_clerks_words(clerk):
    clerk(
        status=422,
        body={
            "errors": [
                {
                    "code": "form_param_format_invalid",
                    "message": "is invalid",
                    "long_message": "first_name must be at most 256 characters",
                    "meta": {"param_name": "first_name"},
                }
            ]
        },
    )
    with pytest.raises(ValidationError) as e:
        user_repository.update_user_name("u_1", "x" * 300, "Lane")
    assert e.value.message == "first_name must be at most 256 characters"
    assert e.value.field == "first_name"


def test_a_422_without_clerks_words_is_still_named(clerk):
    clerk(status=422, body={})
    with pytest.raises(AppError) as e:
        user_repository.update_user_name("u_1", "Mira", "Lane")
    assert e.value.code == "CLERK_UNAVAILABLE"
