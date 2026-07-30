"""shopAssemblyMembers query (#330): the manager assignment picker.

Covers the repository role filter, the resolver's dict->ClerkUser mapping, and `require_role` - which
since #423 is no longer the field's gate (that is the policy table, applied by the schema extension)
but is still what `assignOpenings` calls in its body for the one requirement a field-level table
cannot express: anyone may self-assign, only a manager may assign somebody else.

Resolvers are exercised directly against a ShopAssemblyQueries / ShopAssemblyMutations instance
(matches test_gp_relay_reads.py)."""

import uuid

import pytest

from app.auth import SHOP_ASSEMBLY_MANAGER_ROLE, ForbiddenError, require_role
from app.auth_policy import ROOT_FIELD_POLICY
from app.repositories import shop_assembly_repository, user_repository
from app.schemas import shop_assembly as shop_assembly_module
from app.schemas.inputs import AssignOpeningsInput
from app.schemas.shop_assembly import ShopAssemblyMutations, ShopAssemblyQueries


def _summary(uid, roles):
    return {
        "id": uid,
        "first_name": "First",
        "last_name": uid,
        "email": f"{uid}@example.com",
        "roles": roles,
        "gp_buyer_id": None,
        "image_url": "",
    }


class FakeRequest:
    def __init__(self, token):
        self.headers = {"authorization": f"Bearer {token}"} if token else {}


class FakeInfo:
    def __init__(self, request=None):
        self.context = {"request": request}


def test_shop_assembly_members_filters_by_role():
    users = [
        _summary("mgr", ["Shop Assembly Manager"]),
        _summary("worker", ["Shop Assembly User"]),
        _summary("both", ["Shop Assembly User", "PO User"]),
        _summary("po", ["PO User"]),
        _summary("admin", ["Admin/Manager"]),
        _summary("none", []),
    ]

    members = user_repository.shop_assembly_members(users)

    assert {m["id"] for m in members} == {"mgr", "worker", "both"}


def test_resolver_maps_the_request_roster_to_type(monkeypatch):
    """The roster comes from the request context - the same one the gate checked this caller's
    Shop Assembly Manager role against (ROSTER_BACKED in app/auth_policy.py), so authorizing the
    query and answering it are one Clerk call."""
    roster = [_summary("mgr", ["Shop Assembly Manager"]), _summary("worker", ["Shop Assembly User"])]
    monkeypatch.setattr(shop_assembly_module, "user_roster", lambda context: roster)

    result = ShopAssemblyQueries().shop_assembly_members(FakeInfo())

    assert ROOT_FIELD_POLICY["shopAssemblyMembers"] == SHOP_ASSEMBLY_MANAGER_ROLE
    assert [u.id for u in result] == ["mgr", "worker"]
    assert result[0].email == "mgr@example.com"


def test_require_role_forbids_when_role_absent(monkeypatch):
    """`require_role` is the in-body check, not the field gate. It reads the request-scoped role memo,
    so verify_clerk_token and get_user_roles are what it ends up calling on a cold context."""
    monkeypatch.setattr("app.auth.verify_clerk_token", lambda token: {"sub": "u1"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda uid: ["Shop Assembly User"])

    with pytest.raises(ForbiddenError):
        require_role(FakeInfo(FakeRequest("tok")), SHOP_ASSEMBLY_MANAGER_ROLE)


def test_require_role_allows_when_role_present(monkeypatch):
    monkeypatch.setattr("app.auth.verify_clerk_token", lambda token: {"sub": "u1"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda uid: ["Shop Assembly Manager", "PO User"])

    result = require_role(FakeInfo(FakeRequest("tok")), SHOP_ASSEMBLY_MANAGER_ROLE)

    assert result["user_id"] == "u1"
    assert SHOP_ASSEMBLY_MANAGER_ROLE in result["roles"]


class _FakeSession:
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def commit(self):
        pass


def _bypass_assign_db(monkeypatch):
    """Stub out the DB layer of assign_openings so tests exercise only its authorization branch."""
    monkeypatch.setattr(shop_assembly_module, "SessionLocal", lambda: _FakeSession())
    monkeypatch.setattr(shop_assembly_repository, "assign_openings", lambda *a, **k: [])
    monkeypatch.setattr(shop_assembly_repository, "get_openings_with_items", lambda *a, **k: [])


def _assign_input(assigned_to_user_id):
    return AssignOpeningsInput(
        opening_ids=[str(uuid.uuid4())],
        assigned_to_user_id=assigned_to_user_id,
        assigned_to="Someone",
    )


def test_assign_openings_self_assign_skips_manager_gate(monkeypatch):
    role_calls = []
    monkeypatch.setattr(shop_assembly_module, "current_user", lambda info: {"user_id": "caller"})
    monkeypatch.setattr(shop_assembly_module, "require_role", lambda info, role: role_calls.append(role))
    _bypass_assign_db(monkeypatch)

    ShopAssemblyMutations().assign_openings(FakeInfo(), _assign_input("caller"))

    assert role_calls == []


def test_assign_openings_to_other_requires_manager_role(monkeypatch):
    role_calls = []
    monkeypatch.setattr(shop_assembly_module, "current_user", lambda info: {"user_id": "caller"})
    monkeypatch.setattr(shop_assembly_module, "require_role", lambda info, role: role_calls.append(role))
    _bypass_assign_db(monkeypatch)

    ShopAssemblyMutations().assign_openings(FakeInfo(), _assign_input("other"))

    assert role_calls == [SHOP_ASSEMBLY_MANAGER_ROLE]
