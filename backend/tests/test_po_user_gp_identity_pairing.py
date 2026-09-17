"""A GP buyer identity exists for the PO User role alone (#699, #687 gap 6), enforced on the server.

registerPoInGp gates on the caller's GP buyer identity and nothing about their roles, on the
understanding that only a PO User can have been given one. Until now that pairing was kept only by
the Edit User dialog, so a role removed in the Clerk dashboard or by a direct updateUserRoles call
left an identity behind that could still register POs. These pin the two repository writes that now
keep it: setting an identity needs PO User, and losing PO User clears the identity in the same write.
"""

import pytest

from app.errors import ValidationError
from app.repositories import user_repository
from app.repositories.user_repository import PO_USER_ROLE


class _Resp:
    def __init__(self, payload: dict):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeClerk:
    """Stands in for the httpx client: GET answers with the stored roles, PATCH records the metadata
    patch and answers with the merged user, the way Clerk's /metadata endpoint does."""

    def __init__(self, *, roles: list[str], gp_buyer_id: str | None = None):
        self.metadata: dict = {"roles": roles, "gpBuyerId": gp_buyer_id}
        self.patches: list[dict] = []

    def get(self, path, headers=None):
        return _Resp({"id": "u_target", "public_metadata": dict(self.metadata)})

    def patch(self, path, headers=None, json=None):
        patch = json["public_metadata"]
        self.patches.append(patch)
        for key, value in patch.items():
            if value is None:
                self.metadata.pop(key, None)  # Clerk removes a key whose value is null
            else:
                self.metadata[key] = value
        return _Resp({"id": "u_target", "public_metadata": dict(self.metadata)})


@pytest.fixture
def clerk(monkeypatch):
    def _make(**kw):
        fake = _FakeClerk(**kw)
        monkeypatch.setattr(user_repository, "_client", fake)
        # The header builder refuses to run without a Clerk secret, which CI does not have; nothing
        # here reaches Clerk anyway.
        monkeypatch.setattr(user_repository, "_headers", lambda: {})
        return fake

    return _make


# --- setting an identity ---------------------------------------------------------------------------


def test_an_identity_is_refused_on_an_account_without_po_user(clerk):
    fake = clerk(roles=["Warehouse Staff"])
    with pytest.raises(ValidationError) as exc:
        user_repository.update_user_gp_buyer_id("u_target", "mira")
    assert exc.value.field == "gp_buyer_id"
    assert PO_USER_ROLE in exc.value.message
    assert fake.patches == [], "the refusal must happen before anything reaches Clerk"


def test_an_identity_is_set_on_a_po_user(clerk):
    fake = clerk(roles=[PO_USER_ROLE])
    out = user_repository.update_user_gp_buyer_id("u_target", " mira ")
    assert fake.patches == [{"gpBuyerId": "mira"}]
    assert out["gp_buyer_id"] == "mira"


def test_clearing_an_identity_never_needs_the_role(clerk):
    """The dialog clears with null after unchecking PO User, and roles are saved first - so the role
    is already gone by the time the clear arrives. A clear must not be refused for that."""
    fake = clerk(roles=["Warehouse Staff"], gp_buyer_id="mira")
    out = user_repository.update_user_gp_buyer_id("u_target", None)
    assert fake.patches == [{"gpBuyerId": None}]
    assert out["gp_buyer_id"] is None


# --- changing roles --------------------------------------------------------------------------------


def test_removing_po_user_clears_the_identity_in_the_same_write(clerk):
    fake = clerk(roles=[PO_USER_ROLE], gp_buyer_id="mira")
    out = user_repository.update_user_roles("u_target", ["Warehouse Staff"])
    assert fake.patches == [{"roles": ["Warehouse Staff"], "gpBuyerId": None}]
    assert out["roles"] == ["Warehouse Staff"]
    assert out["gp_buyer_id"] is None


def test_keeping_po_user_leaves_the_identity_alone(clerk):
    fake = clerk(roles=[PO_USER_ROLE], gp_buyer_id="mira")
    out = user_repository.update_user_roles("u_target", [PO_USER_ROLE, "Warehouse Staff"])
    assert fake.patches == [{"roles": [PO_USER_ROLE, "Warehouse Staff"]}]
    assert out["gp_buyer_id"] == "mira"
