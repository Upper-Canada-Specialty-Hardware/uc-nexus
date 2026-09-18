"""The Clerk role migration writes exactly what it says it will, and nothing else (#729).

It is a one-off script run by hand against the production Clerk instance, so there is no second
chance and no undo: a `--plan` that quietly wrote, or a `--grant` that touched somebody outside the
five named accounts, would be found out afterwards by reading Clerk account by account. Every Clerk
call is stubbed here - the roster it reads and the metadata write it makes - so what is asserted is
which writes happen and with what.
"""

import pytest

from app import config
from app.auth import DB_ADMIN_ROLE, NEXUS_ADMIN_ROLE
from app.repositories import user_repository
from scripts.migrate_admin_manager_roles import NEW_ADMIN_EMAILS, RETIRED_ROLE, main

E2E_ID = "user_e2e"


def _user(user_id, email, roles):
    return {
        "id": user_id,
        "first_name": "",
        "last_name": "",
        "email": email,
        "roles": roles,
        "gp_buyer_id": None,
        "company": "TUBC",
        "image_url": "",
    }


def _roster():
    """Four of the five named admins by email, one of them with the tier stacked on, the e2e account
    by id, plus two ordinary holders of the retired role and one account that never held it."""
    return [
        _user("u_1", "jonathanr@ucsh.com", [RETIRED_ROLE]),
        # Deliberately not lower case: Clerk stores what was typed when the account was made.
        _user("u_2", "SteveF@ucsh.com", [RETIRED_ROLE, DB_ADMIN_ROLE]),
        _user("u_3", "josep@ucsh.com", [RETIRED_ROLE]),
        _user("u_4", "jayp@ucsh.com", [RETIRED_ROLE, "PO User"]),
        _user(E2E_ID, "e2e-tester@ucsh.com", [RETIRED_ROLE]),
        _user("u_5", "warehouse@ucsh.com", [RETIRED_ROLE, "Warehouse Manager"]),
        _user("u_6", "dba@ucsh.com", [RETIRED_ROLE, DB_ADMIN_ROLE]),
        _user("u_7", "picker@ucsh.com", ["Warehouse Staff"]),
    ]


@pytest.fixture
def clerk(monkeypatch):
    """A stubbed Clerk: the roster above, and a record of every metadata write attempted."""
    monkeypatch.setattr(config, "CLERK_SECRET_KEY", "sk_test_stub")
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", E2E_ID)
    monkeypatch.setattr(user_repository, "list_users", _roster)

    writes: dict[str, list[str]] = {}

    def _merge(user_id, patch):
        writes[user_id] = patch["roles"]
        return _user(user_id, "", patch["roles"])

    monkeypatch.setattr(user_repository, "_merge_public_metadata", _merge)
    return writes


def test_it_refuses_to_run_without_a_clerk_key(monkeypatch):
    """The key is the only credential it has. Without one every call would fail mid-pass, which is
    the worst place for this script to stop."""
    monkeypatch.setattr(config, "CLERK_SECRET_KEY", "")
    monkeypatch.setattr(user_repository, "list_users", lambda: pytest.fail("Clerk was read anyway"))

    assert main([]) == 2


def test_plan_is_the_default_and_writes_nothing(clerk, capsys):
    assert main([]) == 0
    assert clerk == {}

    out = capsys.readouterr().out
    assert f"7 of 8 Clerk accounts hold {RETIRED_ROLE!r}" in out
    for email in NEW_ADMIN_EMAILS:
        assert email in out
    assert "No changes were made." in out


def test_grant_touches_only_the_five_and_leaves_the_retired_role_alone(clerk):
    assert main(["--grant"]) == 0

    assert set(clerk) == {"u_1", "u_2", "u_3", "u_4", E2E_ID}
    assert clerk["u_1"] == [RETIRED_ROLE, NEXUS_ADMIN_ROLE]
    # Case-insensitive email match, and the DB Admin tier is carried across untouched.
    assert clerk["u_2"] == [RETIRED_ROLE, DB_ADMIN_ROLE, NEXUS_ADMIN_ROLE]
    assert clerk["u_4"] == [RETIRED_ROLE, "PO User", NEXUS_ADMIN_ROLE]


def test_grant_is_idempotent(clerk, monkeypatch):
    """Re-running it after the first pass must be a no-op, not a second copy of the role."""
    already = _roster()
    already[0] = _user("u_1", "jonathanr@ucsh.com", [RETIRED_ROLE, NEXUS_ADMIN_ROLE])
    monkeypatch.setattr(user_repository, "list_users", lambda: already)

    assert main(["--grant"]) == 0
    assert "u_1" not in clerk


def test_grant_refuses_to_write_when_a_named_account_is_missing(clerk, monkeypatch, capsys):
    """A partial grant is the outcome worth avoiding: some admins carried across the deploy and some
    not, with no way to tell which without reading Clerk account by account."""
    monkeypatch.setattr(user_repository, "list_users", lambda: [u for u in _roster() if u["id"] != "u_3"])

    assert main(["--grant"]) == 1
    assert clerk == {}
    assert "josep@ucsh.com" in capsys.readouterr().out


def test_grant_refuses_when_the_e2e_account_is_not_configured(clerk, monkeypatch):
    monkeypatch.setattr(config, "E2E_CLERK_USER_ID", "")

    assert main(["--grant"]) == 1
    assert clerk == {}


def test_strip_removes_the_retired_role_from_everyone(clerk):
    assert main(["--strip"]) == 0

    # Every holder, and nobody else - u_7 never had it.
    assert set(clerk) == {"u_1", "u_2", "u_3", "u_4", E2E_ID, "u_5", "u_6"}
    assert clerk["u_1"] == []
    assert clerk["u_5"] == ["Warehouse Manager"]


def test_strip_takes_db_admin_from_anyone_left_without_the_cross_tenant_role(clerk, capsys):
    """The tier is stacked, never standalone. An account left holding only DB Admin could reach
    neither the Database Access page nor the roster its mint dialog reads."""
    assert main(["--strip"]) == 0

    assert clerk["u_6"] == []
    out = capsys.readouterr().out
    assert "dba@ucsh.com" in out
    assert DB_ADMIN_ROLE in out


def test_strip_keeps_db_admin_where_the_grant_pass_already_stacked_it(clerk, monkeypatch):
    """The two passes in order: --grant put UC Nexus Admin on u_2, so the strip leaves the tier."""
    stacked = _roster()
    stacked[1] = _user("u_2", "SteveF@ucsh.com", [RETIRED_ROLE, DB_ADMIN_ROLE, NEXUS_ADMIN_ROLE])
    monkeypatch.setattr(user_repository, "list_users", lambda: stacked)

    assert main(["--strip"]) == 0
    assert clerk["u_2"] == [DB_ADMIN_ROLE, NEXUS_ADMIN_ROLE]


def test_strip_is_idempotent(clerk, monkeypatch):
    monkeypatch.setattr(
        user_repository,
        "list_users",
        lambda: [_user("u_1", "jonathanr@ucsh.com", [NEXUS_ADMIN_ROLE]), _user("u_7", "picker@ucsh.com", [])],
    )

    assert main(["--strip"]) == 0
    assert clerk == {}
