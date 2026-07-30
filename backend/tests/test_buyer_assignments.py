"""Buyer assignments (issue #216): CRUD + strict per-project enforcement for project POs.

Cost codes are NOT part of this gate. They were once, and the test that used to sit here asserted an
undesignated code was refused; the designation hid valid GP cost codes from purchasers, so it was
removed. `test_validate_allows_any_cost_code` is that test inverted, and it is the regression guard -
if per-buyer cost-code filtering ever comes back, it fails."""

import uuid

import pytest

from app.errors import NotFoundError, ValidationError
from app.models.project import Project
from app.repositories import buyer_repository
from app.schemas.po import _assert_buyer_identity


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def test_save_assignment_upserts_one_row_per_buyer(db_session):
    p1 = _make_project(db_session)
    p2 = _make_project(db_session)

    first = buyer_repository.save_assignment(db_session, "  mira ", [p1.id])
    assert first.buyer_id == "mira"
    assert [p.id for p in first.projects] == [p1.id]

    second = buyer_repository.save_assignment(db_session, "mira", [p1.id, p2.id])
    assert second.id == first.id  # updated in place, not duplicated
    assert {p.id for p in second.projects} == {p1.id, p2.id}


def test_save_assignment_rejects_unknown_project(db_session):
    with pytest.raises(NotFoundError):
        buyer_repository.save_assignment(db_session, "mira", [uuid.uuid4()])


def test_delete_assignment(db_session):
    p = _make_project(db_session)
    buyer_repository.save_assignment(db_session, "mira", [p.id])
    buyer_repository.delete_assignment(db_session, "mira")
    assert buyer_repository.get_assignment(db_session, "mira") is None
    with pytest.raises(NotFoundError):
        buyer_repository.delete_assignment(db_session, "mira")


def test_validate_stock_po_is_not_gated(db_session):
    # No assignment rows at all - a stock PO (no project) is still allowed.
    buyer_repository.validate_buyer_can_order(db_session, "mira", None)


def test_validate_rejects_unassigned_buyer(db_session):
    p = _make_project(db_session)
    with pytest.raises(ValidationError) as exc:
        buyer_repository.validate_buyer_can_order(db_session, "mira", p.id)
    assert exc.value.field == "buyer_id"


def test_validate_rejects_project_outside_assignment(db_session):
    assigned = _make_project(db_session)
    other = _make_project(db_session)
    buyer_repository.save_assignment(db_session, "mira", [assigned.id])
    with pytest.raises(ValidationError) as exc:
        buyer_repository.validate_buyer_can_order(db_session, "mira", other.id)
    assert exc.value.field == "project_id"


def test_validate_allows_any_cost_code(db_session):
    """The happy path, doubling as the regression guard for the removal: assignment carries no
    cost-code state at all, so the gate cannot narrow the register-PO dropdown to a hand-maintained
    subset again. (End-to-end coverage that an arbitrary code registers lives in
    test_register_po_in_gp.test_prepare_register_po_accepts_any_cost_code.)"""
    p = _make_project(db_session)
    assignment = buyer_repository.save_assignment(db_session, "mira", [p.id])
    assert not hasattr(assignment, "cost_codes")
    buyer_repository.validate_buyer_can_order(db_session, "mira", p.id)


def test_assert_buyer_identity():
    with pytest.raises(ValidationError):
        _assert_buyer_identity(None, "mira")
    with pytest.raises(ValidationError):
        _assert_buyer_identity("", "mira")
    with pytest.raises(ValidationError):
        _assert_buyer_identity("mira", "steve")
    # case-insensitive, whitespace-tolerant match (GP BUYERID is char-padded uppercase)
    _assert_buyer_identity("MIRA", " mira ")
