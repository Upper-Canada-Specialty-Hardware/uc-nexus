"""Buyer assignments (issue #216): CRUD + strict project/cost-code enforcement for project POs."""

import uuid

import pytest

from app.errors import NotFoundError, ValidationError
from app.models.project import Project
from app.repositories import buyer_repository
from app.schemas.mutations import _assert_buyer_identity


def _make_project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:6]}", description="Test")
    session.add(p)
    session.flush()
    return p


def test_save_assignment_upserts_one_row_per_buyer(db_session):
    p1 = _make_project(db_session)
    p2 = _make_project(db_session)

    first = buyer_repository.save_assignment(db_session, "  mira ", [p1.id], ["310-000", " 310-000", ""])
    assert first.buyer_id == "mira"
    assert first.cost_codes == ["310-000"]  # trimmed + deduped + blanks dropped
    assert [p.id for p in first.projects] == [p1.id]

    second = buyer_repository.save_assignment(db_session, "mira", [p1.id, p2.id], ["210-200"])
    assert second.id == first.id  # updated in place, not duplicated
    assert {p.id for p in second.projects} == {p1.id, p2.id}
    assert second.cost_codes == ["210-200"]


def test_save_assignment_rejects_unknown_project(db_session):
    with pytest.raises(NotFoundError):
        buyer_repository.save_assignment(db_session, "mira", [uuid.uuid4()], [])


def test_delete_assignment(db_session):
    p = _make_project(db_session)
    buyer_repository.save_assignment(db_session, "mira", [p.id], [])
    buyer_repository.delete_assignment(db_session, "mira")
    assert buyer_repository.get_assignment(db_session, "mira") is None
    with pytest.raises(NotFoundError):
        buyer_repository.delete_assignment(db_session, "mira")


def test_validate_stock_po_is_not_gated(db_session):
    # No assignment rows at all - a stock PO (no project) is still allowed.
    buyer_repository.validate_buyer_can_order(db_session, "mira", None, None)


def test_validate_rejects_unassigned_buyer(db_session):
    p = _make_project(db_session)
    with pytest.raises(ValidationError) as exc:
        buyer_repository.validate_buyer_can_order(db_session, "mira", p.id, "210-200-2")
    assert exc.value.field == "buyer_id"


def test_validate_rejects_project_outside_assignment(db_session):
    assigned = _make_project(db_session)
    other = _make_project(db_session)
    buyer_repository.save_assignment(db_session, "mira", [assigned.id], ["210-200"])
    with pytest.raises(ValidationError) as exc:
        buyer_repository.validate_buyer_can_order(db_session, "mira", other.id, "210-200-2")
    assert exc.value.field == "project_id"


def test_validate_rejects_undesignated_cost_code(db_session):
    p = _make_project(db_session)
    buyer_repository.save_assignment(db_session, "mira", [p.id], ["310-000"])
    with pytest.raises(ValidationError) as exc:
        # '210-200-2' -> code part '210-200', not in the designated list
        buyer_repository.validate_buyer_can_order(db_session, "mira", p.id, "210-200-2")
    assert exc.value.field == "cost_code"


def test_validate_happy_path(db_session):
    p = _make_project(db_session)
    buyer_repository.save_assignment(db_session, "mira", [p.id], ["210-200", "310-000"])
    buyer_repository.validate_buyer_can_order(db_session, "mira", p.id, "210-200-2")


def test_assert_buyer_identity():
    with pytest.raises(ValidationError):
        _assert_buyer_identity(None, "mira")
    with pytest.raises(ValidationError):
        _assert_buyer_identity("", "mira")
    with pytest.raises(ValidationError):
        _assert_buyer_identity("mira", "steve")
    # case-insensitive, whitespace-tolerant match (GP BUYERID is char-padded uppercase)
    _assert_buyer_identity("MIRA", " mira ")
