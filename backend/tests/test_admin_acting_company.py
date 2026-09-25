"""A UC NEXUS ADMIN works in one GP company at a time (#845).

The app bar's company switcher sends the chosen company as the `X-Nexus-Company` header, and
`tenant_scope` answers it for an admin instead of None. Four properties matter and each has a test:

  - the header scopes an admin, and its absence leaves them unscoped exactly as before;
  - it is IGNORED for everybody else - it must never be a way out of a caller's own company;
  - an admin naming a company Nexus does not know is refused, not scoped to an empty tenant;
  - the company-less tools (user management) stay cross-tenant whatever the header says.

None of these touch Postgres: the database half of the company list is monkeypatched, and the relay
half is a stand-in gateway. So the whole file runs locally as well as in CI.
"""

import asyncio
from types import SimpleNamespace

import pytest

from app.auth import NEXUS_ADMIN_ROLE, TENANT_OWNER_ROLE, ForbiddenError, tenant_scope
from app.auth_policy import ROOT_FIELD_POLICY
from app.errors import ValidationError
from app.schemas import relay as relay_module
from app.services import nexus_companies
from main import schema


class _Request:
    def __init__(self, company: str | None = None):
        self.headers = {"authorization": "Bearer tok"}
        if company is not None:
            self.headers["X-Nexus-Company"] = company


def _ctx(roles, *, company=None, header=None):
    """A context with the auth memos seeded, so nothing reaches Clerk."""
    return {
        "request": _Request(header),
        "_auth_user_id": "u_test",
        "_auth_roles": roles,
        "_auth_company": company,
    }


class _Info:
    def __init__(self, roles, *, company=None, header=None):
        self.context = _ctx(roles, company=company, header=header)


@pytest.fixture
def companies(monkeypatch):
    """The relay serves TUBC and UCSH (with GP names); projects exist under TUBC and OLDCO, a company
    the relay does not serve. Counts the database lookups so the memo can be checked."""
    gateway = SimpleNamespace(companies=["TUBC", "UCSH"], company_names={"TUBC": "Test UBC", "UCSH": ""})
    monkeypatch.setattr(nexus_companies, "relay_gateway", gateway)
    lookups = []

    def _project_companies():
        lookups.append(1)
        return {"TUBC", "OLDCO"}

    monkeypatch.setattr(nexus_companies, "project_companies", _project_companies)
    return SimpleNamespace(gateway=gateway, lookups=lookups)


# --- tenant_scope ------------------------------------------------------------------------------


def test_an_admin_with_the_header_is_scoped_to_that_company(companies):
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="UCSH")) == "UCSH"


def test_the_header_is_normalized_like_a_company_on_an_account(companies):
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="  ucsh ")) == "UCSH"


def test_a_company_known_only_from_its_projects_is_accepted(companies):
    """The relay being down must not lock an admin out of a company's projects."""
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="OLDCO")) == "OLDCO"


def test_an_admin_without_the_header_is_unscoped_as_before(companies):
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], company="TUBC")) is None
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="   ")) is None


def test_a_scoped_caller_naming_another_company_stays_in_their_own(companies):
    """Never an escalation path: a TENANT OWNER of TUBC sending UCSH is still TUBC."""
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", header="UCSH")) == "TUBC"
    assert tenant_scope(_Info(["Warehouse Manager"], company="TUBC", header="UCSH")) == "TUBC"


def test_an_unassigned_caller_is_still_refused_whatever_the_header(companies):
    with pytest.raises(ForbiddenError):
        tenant_scope(_Info(["Warehouse Manager"], company=None, header="TUBC"))


def test_an_admin_naming_an_unknown_company_is_refused(companies):
    with pytest.raises(ValidationError, match="Unknown GP company 'NOPE'"):
        tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="nope"))


def test_the_header_check_is_memoised_per_request(companies):
    info = _Info([NEXUS_ADMIN_ROLE], header="OLDCO")
    for _ in range(5):
        assert tenant_scope(info) == "OLDCO"
    assert len(companies.lookups) == 1


def test_a_refused_header_is_memoised_too(companies):
    info = _Info([NEXUS_ADMIN_ROLE], header="NOPE")
    for _ in range(3):
        with pytest.raises(ValidationError):
            tenant_scope(info)
    assert len(companies.lookups) == 1


def test_a_relay_served_company_costs_no_database_lookup(companies):
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="UCSH")) == "UCSH"
    assert companies.lookups == []


def test_cross_tenant_scope_ignores_the_header_for_an_admin(companies):
    assert tenant_scope(_Info([NEXUS_ADMIN_ROLE], header="UCSH"), cross_tenant=True) is None


def test_cross_tenant_scope_changes_nothing_for_a_scoped_caller(companies):
    assert tenant_scope(_Info([TENANT_OWNER_ROLE], company="TUBC", header="UCSH"), cross_tenant=True) == "TUBC"


# --- the company-less tools --------------------------------------------------------------------

_ROSTER = [
    {
        "id": "u_test",
        "first_name": "Ada",
        "last_name": "Admin",
        "email": "",
        "roles": [NEXUS_ADMIN_ROLE],
        "company": "TUBC",
        "image_url": "",
    },
    {
        "id": "u_other",
        "first_name": "Uma",
        "last_name": "User",
        "email": "",
        "roles": [],
        "company": "UCSH",
        "image_url": "",
    },
]


def test_the_users_roster_stays_cross_tenant_for_an_admin_with_the_header(companies):
    context = _ctx([NEXUS_ADMIN_ROLE], header="TUBC")
    context["_auth_user_roster"] = _ROSTER
    result = asyncio.run(schema.execute("{ users { id } }", context_value=context))
    assert result.errors is None
    assert {u["id"] for u in result.data["users"]} == {"u_test", "u_other"}


def test_a_user_edit_reaches_another_company_for_an_admin_with_the_header(companies, monkeypatch):
    """`_require_target_in_scope` is cross-tenant: the admin need not switch company to edit an account."""
    from app.schemas import user as user_module

    monkeypatch.setattr(user_module.user_repository, "get_user_company", lambda user_id: "UCSH")
    assert user_module._require_target_in_scope(_Info([NEXUS_ADMIN_ROLE], header="TUBC"), "u_other") is None


def test_gp_reads_follow_the_header(companies, monkeypatch):
    """A passthrough GP read is working data, so it follows the switcher: an admin in TUBC reading
    UCSH's job master is refused like a TUBC user would be."""
    monkeypatch.setattr(
        relay_module, "relay_gateway", SimpleNamespace(companies=["TUBC", "UCSH"], companies_error=None)
    )
    info = _Info([NEXUS_ADMIN_ROLE], header="TUBC")
    assert relay_module.resolve_gp_company(info, "TUBC") == "TUBC"
    with pytest.raises(ValidationError):
        relay_module.resolve_gp_company(info, "UCSH")


# --- nexusCompanies ----------------------------------------------------------------------------


def test_nexus_companies_is_uc_nexus_admin_only():
    assert ROOT_FIELD_POLICY["nexusCompanies"] == NEXUS_ADMIN_ROLE


def test_nexus_companies_is_the_union_sorted_and_named(companies):
    result = asyncio.run(schema.execute("{ nexusCompanies { id name } }", context_value=_ctx([NEXUS_ADMIN_ROLE])))
    assert result.errors is None
    assert result.data["nexusCompanies"] == [
        {"id": "OLDCO", "name": "OLDCO"},
        {"id": "TUBC", "name": "Test UBC"},
        {"id": "UCSH", "name": "UCSH"},
    ]


def test_nexus_companies_works_while_the_relay_is_down(companies):
    companies.gateway.companies = []
    companies.gateway.company_names = {}
    result = asyncio.run(schema.execute("{ nexusCompanies { id name } }", context_value=_ctx([NEXUS_ADMIN_ROLE])))
    assert result.errors is None
    assert [c["id"] for c in result.data["nexusCompanies"]] == ["OLDCO", "TUBC"]


def test_nexus_companies_is_refused_to_a_tenant_owner(companies):
    result = asyncio.run(
        schema.execute("{ nexusCompanies { id } }", context_value=_ctx([TENANT_OWNER_ROLE], company="TUBC"))
    )
    assert result.errors is not None
    assert result.errors[0].extensions["code"] == "FORBIDDEN"
