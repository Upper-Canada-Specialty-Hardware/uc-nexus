"""The "DB Admin" tier stays exclusive and stacked (db-admin-postgres-access).

`updateUserRoles` is Admin/Manager-gated by ROOT_FIELD_POLICY, which is not enough on its own: DB
Admin sits ABOVE Admin/Manager, so without a body guard any admin could hand themselves the tier that
mints internet-reachable Postgres logins - exclusive in name only. `_enforce_db_admin_grant_rules`
closes that, and it refuses a standalone DB Admin so the stacking invariant holds for EVERY caller,
not just the UI. These run the real mutation through the real schema and assert both directions.
"""

import asyncio

from app import auth
from app.auth import ADMIN_ROLE, DB_ADMIN_ROLE
from app.repositories import user_repository
from main import schema


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _run(new_roles, *, caller_roles, target_roles, monkeypatch):
    """Run updateUserRoles for target `u_target` setting `new_roles`, with the caller holding
    `caller_roles` and the target currently holding `target_roles`. Returns (result, captured), where
    `captured["roles"]` is set only if the write actually reached Clerk."""
    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_caller"})

    def _get_roles(user_id):
        return caller_roles if user_id == "u_caller" else target_roles

    monkeypatch.setattr(user_repository, "get_user_roles", _get_roles)

    captured: dict = {}

    def _update(user_id, roles):
        captured["roles"] = roles
        return {
            "id": user_id,
            "first_name": "",
            "last_name": "",
            "email": "",
            "roles": roles,
            "gp_buyer_id": None,
            "image_url": "",
        }

    monkeypatch.setattr(user_repository, "update_user_roles", _update)

    roles_arg = "[" + ", ".join(f'"{r}"' for r in new_roles) + "]"
    query = f'mutation {{ updateUserRoles(userId: "u_target", roles: {roles_arg}) {{ id roles }} }}'
    result = asyncio.run(schema.execute(query, context_value={"request": _FakeRequest()}))
    return result, captured


def _codes(result) -> set:
    return {(e.extensions or {}).get("code") for e in (result.errors or [])}


def _messages(result) -> set:
    return {e.message for e in (result.errors or [])}


def test_a_plain_admin_cannot_grant_db_admin(monkeypatch):
    """The role-grant hole: updateUserRoles is admin-gated, so an admin who is NOT a DB Admin must not
    be able to add the tier - to themselves or anyone."""
    result, captured = _run(
        [ADMIN_ROLE, DB_ADMIN_ROLE],
        caller_roles=[ADMIN_ROLE],
        target_roles=[ADMIN_ROLE],
        monkeypatch=monkeypatch,
    )

    assert _codes(result) == {"FORBIDDEN"}
    assert _messages(result) == {f"only a {DB_ADMIN_ROLE} may grant or remove {DB_ADMIN_ROLE}"}
    assert "roles" not in captured, "the write happened despite the refusal"


def test_a_db_admin_can_grant_db_admin_when_stacked_on_admin(monkeypatch):
    """The other direction: a DB Admin may hand the tier out, as long as Admin/Manager comes with it."""
    result, captured = _run(
        [ADMIN_ROLE, DB_ADMIN_ROLE],
        caller_roles=[ADMIN_ROLE, DB_ADMIN_ROLE],
        target_roles=[ADMIN_ROLE],
        monkeypatch=monkeypatch,
    )

    assert result.errors is None, f"a DB Admin was refused the grant: {_messages(result)}"
    assert captured["roles"] == [ADMIN_ROLE, DB_ADMIN_ROLE]


def test_db_admin_without_admin_manager_is_refused_for_everyone(monkeypatch):
    """Stacking invariant. Even a DB Admin cannot create a standalone one - it would be stranded
    outside the Admin/Manager-gated admin shell the page lives in."""
    result, captured = _run(
        [DB_ADMIN_ROLE],
        caller_roles=[ADMIN_ROLE, DB_ADMIN_ROLE],
        target_roles=[ADMIN_ROLE],
        monkeypatch=monkeypatch,
    )

    assert _codes(result) == {"FORBIDDEN"}
    assert _messages(result) == {f"{DB_ADMIN_ROLE} requires {ADMIN_ROLE}; it cannot be held on its own"}
    assert "roles" not in captured


def test_a_plain_admin_cannot_strip_db_admin_from_a_db_admin(monkeypatch):
    """The mirror of the grant hole: removing the tier is a DB-Admin-only act too, so an admin cannot
    demote a DB Admin out from under them."""
    result, captured = _run(
        [ADMIN_ROLE],
        caller_roles=[ADMIN_ROLE],
        target_roles=[ADMIN_ROLE, DB_ADMIN_ROLE],
        monkeypatch=monkeypatch,
    )

    assert _codes(result) == {"FORBIDDEN"}
    assert _messages(result) == {f"only a {DB_ADMIN_ROLE} may grant or remove {DB_ADMIN_ROLE}"}
    assert "roles" not in captured


def test_a_plain_admin_may_edit_a_db_admin_user_without_touching_the_tier(monkeypatch):
    """A non-DB-Admin editing a DB Admin's OTHER roles must still work, as long as the DB Admin bit is
    unchanged - the guard gates the tier, not every edit to a user who holds it."""
    result, captured = _run(
        [ADMIN_ROLE, DB_ADMIN_ROLE, "PO User"],
        caller_roles=[ADMIN_ROLE],
        target_roles=[ADMIN_ROLE, DB_ADMIN_ROLE],
        monkeypatch=monkeypatch,
    )

    assert result.errors is None, f"an unrelated edit to a DB Admin user was refused: {_messages(result)}"
    assert captured["roles"] == [ADMIN_ROLE, DB_ADMIN_ROLE, "PO User"]


def test_a_db_admin_can_remove_the_tier(monkeypatch):
    result, captured = _run(
        [ADMIN_ROLE],
        caller_roles=[ADMIN_ROLE, DB_ADMIN_ROLE],
        target_roles=[ADMIN_ROLE, DB_ADMIN_ROLE],
        monkeypatch=monkeypatch,
    )

    assert result.errors is None, f"a DB Admin was refused a removal: {_messages(result)}"
    assert captured["roles"] == [ADMIN_ROLE]


def test_an_ordinary_role_edit_by_a_plain_admin_still_works(monkeypatch):
    """The guard adds no friction to the common path: an admin editing a normal user's roles, none of
    them the tier, is untouched and pays no target-roles read gate it cannot pass."""
    result, captured = _run(
        [ADMIN_ROLE, "Warehouse Staff"],
        caller_roles=[ADMIN_ROLE],
        target_roles=["Warehouse Staff"],
        monkeypatch=monkeypatch,
    )

    assert result.errors is None, f"an ordinary role edit was refused: {_messages(result)}"
    assert captured["roles"] == [ADMIN_ROLE, "Warehouse Staff"]
