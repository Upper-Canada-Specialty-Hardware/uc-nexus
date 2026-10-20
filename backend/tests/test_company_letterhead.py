"""What a GP company prints as itself: GP's name and its own address (#1689).

Ruled on #1762: the name is GP's, as the relay reports it; each company prints its own address, typed
in Nexus; a company with none yet prints the shared from-address below its old name line.
"""

import pytest

from app.demo import DEMO_COMPANY, DEMO_COMPANY_NAME
from app.errors import ValidationError
from app.models.company_letterhead import CompanyLetterhead
from app.repositories import company_letterhead_repository as letterhead
from app.repositories import po_document_settings_repository
from app.services.relay_gateway import gateway as relay_gateway


@pytest.fixture
def relay_names(monkeypatch):
    """The names the connected relay reports; empty is a relay that is down."""
    names: dict[str, str] = {}
    monkeypatch.setattr(type(relay_gateway), "company_names", property(lambda self: dict(names)))
    return names


def test_the_live_relay_name_is_printed(db_session, relay_names):
    relay_names["TUBC"] = "Test UBC"

    assert letterhead.printed_name(db_session, "TUBC") == "Test UBC"


def test_a_kept_name_is_printed_while_the_relay_is_down(db_session, relay_names):
    letterhead.record_gp_names(db_session, {"TUBC": "Test UBC"})
    db_session.flush()

    assert letterhead.printed_name(db_session, "TUBC") == "Test UBC"


def test_a_company_gp_never_named_prints_its_code(db_session, relay_names):
    assert letterhead.printed_name(db_session, "ZZZ1") == "ZZZ1"


def test_the_demo_company_prints_its_own_name(db_session, relay_names):
    assert letterhead.printed_name(db_session, DEMO_COMPANY) == DEMO_COMPANY_NAME


def test_a_renamed_company_keeps_the_new_name(db_session, relay_names):
    letterhead.record_gp_names(db_session, {"TUBC": "Test UBC"})
    letterhead.record_gp_names(db_session, {"TUBC": "Test UBC Ltd."})
    db_session.flush()

    assert db_session.get(CompanyLetterhead, "TUBC").gp_name == "Test UBC Ltd."


def test_a_name_kept_does_not_touch_the_address(db_session, relay_names):
    letterhead.set_address(db_session, "TUBC", "1 Main St\nVictoria, BC")
    letterhead.record_gp_names(db_session, {"TUBC": "Test UBC"})
    db_session.flush()
    db_session.expire_all()

    assert db_session.get(CompanyLetterhead, "TUBC").address == "1 Main St\nVictoria, BC"


def test_a_company_with_its_own_address_prints_it(db_session, relay_names):
    relay_names["TUBC"] = "Test UBC"

    result = letterhead.set_address(db_session, "TUBC", "  1 Main St\nVictoria, BC  ")

    assert result == {"company": "TUBC", "name": "Test UBC", "address": "1 Main St\nVictoria, BC"}


def test_a_company_without_one_prints_the_shared_address_below_its_name_line(db_session, relay_names):
    po_document_settings_repository.update_settings(
        db_session, company_from_address="Old Shared Name\nUnit 1 - 7100 Warden Avenue\nMarkham, ON"
    )

    result = letterhead.get_letterhead(db_session, "ZZZ2")

    assert result["address"] == "Unit 1 - 7100 Warden Avenue\nMarkham, ON"


def test_a_blank_address_goes_back_to_the_shared_one(db_session, relay_names):
    po_document_settings_repository.update_settings(db_session, company_from_address="Shared\nShared St")
    letterhead.set_address(db_session, "TUBC", "1 Main St")

    result = letterhead.set_address(db_session, "TUBC", "   ")

    assert result["address"] == "Shared St"


def test_an_overlong_address_is_refused(db_session, relay_names):
    with pytest.raises(ValidationError) as exc:
        letterhead.set_address(db_session, "TUBC", "x" * (letterhead.MAX_ADDRESS_LENGTH + 1))

    assert exc.value.field == "address"


# --- whose letterhead a caller reads (no database) ----------------------------------------------


class _Request:
    def __init__(self, company: str | None = None):
        self.headers = {"authorization": "Bearer tok"}
        if company is not None:
            self.headers["X-Nexus-Company"] = company


class _Info:
    """A context with the auth memos seeded, so nothing reaches Clerk."""

    def __init__(self, roles, *, company=None, header=None):
        self.context = {
            "request": _Request(header),
            "_auth_user_id": "u_test",
            "_auth_roles": roles,
            "_auth_company": company,
        }


@pytest.fixture
def known(monkeypatch):
    from app.services import nexus_companies

    monkeypatch.setattr(nexus_companies, "is_known_company", lambda c: c in {"TUBC", "UCSH"})


def test_a_scoped_caller_reads_its_own_company(known):
    from app.schemas.po import _letterhead_company

    assert _letterhead_company(_Info(["PO User"], company="TUBC"), None) == "TUBC"
    assert _letterhead_company(_Info(["PO User"], company="TUBC"), "tubc") == "TUBC"


def test_a_scoped_caller_naming_another_company_is_refused(known):
    from app.auth import ForbiddenError
    from app.schemas.po import _letterhead_company

    with pytest.raises(ForbiddenError):
        _letterhead_company(_Info(["PO User"], company="TUBC"), "UCSH")


def test_an_unscoped_admin_names_the_company(known):
    from app.auth import NEXUS_ADMIN_ROLE
    from app.schemas.po import _letterhead_company

    assert _letterhead_company(_Info([NEXUS_ADMIN_ROLE]), "UCSH") == "UCSH"
    with pytest.raises(ValidationError):
        _letterhead_company(_Info([NEXUS_ADMIN_ROLE]), None)
    with pytest.raises(ValidationError):
        _letterhead_company(_Info([NEXUS_ADMIN_ROLE]), "NOPE")
