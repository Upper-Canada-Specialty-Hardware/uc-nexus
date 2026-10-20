"""A retired role can no longer be granted (#1390).

Hardware Schedule Import opened nothing, and the product owner retired it. The User Management page no
longer offers it; `_refuse_retired_roles` is what holds a direct `updateUserRoles` to the same rule,
while still letting an account that holds it be saved until the strip script takes it off.
"""

import asyncio

from app import auth
from app.auth import NEXUS_ADMIN_ROLE
from app.repositories import user_repository
from main import schema

RETIRED = "Hardware Schedule Import"


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _run(new_roles, *, target_roles, monkeypatch):
    """Run updateUserRoles as a UC Nexus Admin on `u_target`, who holds `target_roles` now. Returns
    (result, captured); `captured["roles"]` is set only if the write reached Clerk."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})
    monkeypatch.setattr(
        user_repository,
        "get_user_roles",
        lambda user_id: [NEXUS_ADMIN_ROLE] if user_id == "u_caller" else target_roles,
    )
    captured: dict = {}

    def _update(user_id, roles):
        captured["roles"] = roles
        return {"id": user_id, "first_name": "", "last_name": "", "email": "", "roles": roles, "image_url": ""}

    monkeypatch.setattr(user_repository, "update_user_roles", _update)

    roles_arg = "[" + ", ".join(f'"{r}"' for r in new_roles) + "]"
    query = f'mutation {{ updateUserRoles(userId: "u_target", roles: {roles_arg}) {{ id roles }} }}'
    result = asyncio.run(schema.execute(query, context_value={"request": _FakeRequest()}))
    return result, captured


def test_granting_the_retired_role_is_refused(monkeypatch):
    result, captured = _run(["PO User", RETIRED], target_roles=["PO User"], monkeypatch=monkeypatch)

    assert {(e.extensions or {}).get("code") for e in result.errors or []} == {"FORBIDDEN"}
    assert {e.message for e in result.errors} == {f"{RETIRED} is retired and can no longer be granted"}
    assert "roles" not in captured


def test_an_account_that_still_holds_it_can_be_saved(monkeypatch):
    """Before the strip reaches it, editing such an account's other roles is not refused."""
    result, captured = _run([RETIRED, "Warehouse Staff"], target_roles=[RETIRED], monkeypatch=monkeypatch)

    assert result.errors is None, result.errors
    assert captured["roles"] == [RETIRED, "Warehouse Staff"]


def test_taking_it_off_is_allowed(monkeypatch):
    result, captured = _run(["PO User"], target_roles=["PO User", RETIRED], monkeypatch=monkeypatch)

    assert result.errors is None, result.errors
    assert captured["roles"] == ["PO User"]
