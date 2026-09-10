"""Registering a GP-born PO's lines in Nexus: identity, the tie, and what is refused.

A GP PO LINE ITEM that Nexus mirrored carries GP's own item number and description. Registering it
writes the schedule's hardware category and product code over those two fields and makes the line a
NEXUS REGISTERED LINE, so the OPEN-POS SYNC leaves them alone from then on. On a PO with a project it
also ties the schedule's hardware to the line, for the outstanding quantity only.

DB-backed (db_session). The schema half runs through the built Strawberry schema with the caller's
company stubbed, the way the other schema tests stub it (#637).
"""

import asyncio
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import auth
from app.errors import InvalidStateTransitionError, ValidationError
from app.models.enums import HardwareItemState, POOrigin, POStatus
from app.models.hardware import HardwareItem
from app.models.project import Opening, Project
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.repositories import po_repository, user_repository
from main import schema

COMPANY = "TUBC"
CATEGORY = "Hinges"
CODE = "HG-100"


@pytest.fixture
def project(db_session):
    p = Project(id=uuid.uuid4(), project_id=f"J-{uuid.uuid4().hex[:6]}", description="Job", company=COMPANY)
    db_session.add(p)
    db_session.flush()
    return p


def _schedule_units(session, project, *, quantity: int, category: str = CATEGORY, code: str = CODE) -> None:
    """`quantity` AVAILABLE schedule units, one per opening, so the greedy tie can take any subset."""
    for n in range(quantity):
        opening = Opening(id=uuid.uuid4(), project_id=project.id, opening_number=f"{n + 1:03d}")
        session.add(opening)
        session.flush()
        session.add(
            HardwareItem(
                id=uuid.uuid4(),
                project_id=project.id,
                opening_id=opening.id,
                hardware_category=category,
                product_code=code,
                item_quantity=1,
                state=HardwareItemState.AVAILABLE,
            )
        )
    session.flush()


def _mirrored_po(
    session,
    *,
    project=None,
    status=POStatus.GP_REGISTERED,
    origin=POOrigin.GP,
    ordered=5,
    received=0,
):
    po = PurchaseOrder(
        id=uuid.uuid4(),
        company=COMPANY,
        gp_company=COMPANY,
        po_number=f"PO{uuid.uuid4().hex[:8].upper()}",
        request_number=None,
        origin=origin,
        project_id=project.id if project is not None else None,
        status=status,
    )
    session.add(po)
    session.flush()
    line = POLineItem(
        id=uuid.uuid4(),
        po_id=po.id,
        gp_line_ord=16384,
        # What GP holds: a cost bucket as the item number, the part number as the description.
        hardware_category="HD 001 HINGE 4.5 X 4.5",
        product_code="HD 001",
        ordered_quantity=ordered,
        received_quantity=received,
        unit_cost=Decimal("10.00"),
        nexus_registered=False,
    )
    session.add(line)
    session.flush()
    return po, line


def _entry(line, **overrides) -> dict:
    entry = {
        "po_line_item_id": line.id,
        "hardware_category": CATEGORY,
        "product_code": CODE,
        "tie_quantity": 0,
    }
    entry.update(overrides)
    return entry


def _tied_units(session, line) -> int:
    rows = session.scalars(select(HardwareItem).where(HardwareItem.po_line_item_id == line.id)).all()
    return sum(hi.item_quantity for hi in rows)


# --- the tie -----------------------------------------------------------------------------------------


def test_a_line_is_registered_with_the_schedules_identity(db_session, project):
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project)

    po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=5)])

    assert line.hardware_category == CATEGORY
    assert line.product_code == CODE
    assert line.nexus_registered is True


def test_the_tie_covers_the_outstanding_quantity_only(db_session, project):
    # 5 ordered, 2 already received before Nexus knew about the PO: 3 outstanding.
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project, ordered=5, received=2)

    _po, tied = po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=3)])

    assert tied == 3
    assert _tied_units(db_session, line) == 3
    assert all(
        hi.state == HardwareItemState.IN_PO
        for hi in db_session.scalars(select(HardwareItem).where(HardwareItem.po_line_item_id == line.id)).all()
    )


def test_asking_for_more_than_the_outstanding_quantity_is_refused(db_session, project):
    _schedule_units(db_session, project, quantity=10)
    po, line = _mirrored_po(db_session, project=project, ordered=5, received=2)

    with pytest.raises(ValidationError) as exc:
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=4)])

    assert "At most 3" in str(exc.value)
    assert line.nexus_registered is False


def test_asking_for_more_than_the_schedule_has_available_is_refused(db_session, project):
    # Plenty outstanding on the PO, but the schedule only has 2 units of the product left unpurchased.
    _schedule_units(db_session, project, quantity=2)
    po, line = _mirrored_po(db_session, project=project, ordered=5)

    with pytest.raises(ValidationError) as exc:
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=5)])

    assert "At most 2" in str(exc.value)


def test_a_zero_tie_registers_the_identity_and_ties_nothing(db_session, project):
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project)

    _po, tied = po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=0)])

    assert tied == 0
    assert _tied_units(db_session, line) == 0
    assert line.nexus_registered is True


# --- a PO with no project ----------------------------------------------------------------------------


def test_a_stock_po_takes_the_identity_alone(db_session):
    po, line = _mirrored_po(db_session, project=None)

    _po, tied = po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line)])

    assert tied == 0
    assert (line.hardware_category, line.product_code) == (CATEGORY, CODE)
    assert line.nexus_registered is True


def test_a_stock_po_refuses_a_tie_quantity(db_session):
    po, line = _mirrored_po(db_session, project=None)

    with pytest.raises(ValidationError) as exc:
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=1)])

    assert "no project" in str(exc.value)
    assert line.nexus_registered is False


# --- what cannot be registered -----------------------------------------------------------------------


@pytest.mark.parametrize("status", [POStatus.CLOSED, POStatus.CANCELLED])
def test_a_finished_po_cannot_be_registered(db_session, project, status):
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project, status=status)

    with pytest.raises(InvalidStateTransitionError):
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line)])

    assert line.nexus_registered is False


def test_a_nexus_raised_po_has_nothing_to_register(db_session, project):
    po, line = _mirrored_po(db_session, project=project, origin=POOrigin.NEXUS)

    with pytest.raises(InvalidStateTransitionError) as exc:
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line)])

    assert "raised in Nexus" in str(exc.value)


def test_a_line_belonging_to_another_po_is_refused(db_session, project):
    po, _line = _mirrored_po(db_session, project=project)
    _other_po, other_line = _mirrored_po(db_session, project=project)

    with pytest.raises(ValidationError):
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(other_line)])


def test_a_blank_identity_is_refused(db_session, project):
    po, line = _mirrored_po(db_session, project=project)

    with pytest.raises(ValidationError):
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, product_code="  ")])


# --- re-submitting a registered line -----------------------------------------------------------------


def test_a_registered_line_cannot_be_repointed(db_session, project):
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project)
    po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=1)])

    with pytest.raises(ValidationError) as exc:
        po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, product_code="LK-200")])

    assert "already registered" in str(exc.value)
    assert line.product_code == CODE


def test_a_registered_line_accepts_the_same_identity_again(db_session, project):
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project)
    po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=1)])

    _po, tied = po_repository.nexus_register_po_lines(db_session, po.id, [_entry(line, tie_quantity=2)])

    assert tied == 2
    assert _tied_units(db_session, line) == 3


# --- what the schema publishes -----------------------------------------------------------------------


class _FakeRequest:
    def __init__(self, token: str = "tok"):
        self.headers = {"authorization": f"Bearer {token}"}


def _context():
    return {
        "request": _FakeRequest(),
        "_auth_user_id": "u_test",
        "_auth_roles": [],
        "_auth_company": COMPANY,
    }


def _execute(query: str, variables: dict | None = None):
    return asyncio.run(schema.execute(query, variable_values=variables or {}, context_value=_context()))


@pytest.fixture
def signed_in(monkeypatch, db_session):
    """A signed-in caller whose PO resolvers run against the test's own session."""
    from app.schemas import po as po_module

    monkeypatch.setattr(auth, "verify_clerk_token", lambda token: {"sub": "u_test"})
    monkeypatch.setattr(user_repository, "get_user_roles", lambda user_id: [])
    monkeypatch.setattr(user_repository, "get_user_company", lambda user_id: COMPANY)

    class _Borrowed:
        def __enter__(self):
            return db_session

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(po_module, "SessionLocal", _Borrowed)
    # The resolver commits; the fixture's outer transaction is what actually rolls the test back.
    monkeypatch.setattr(db_session, "commit", db_session.flush)
    return db_session


_MUTATION = """
mutation($input: NexusRegisterPoLinesInput!) {
  nexusRegisterPoLines(input: $input) {
    tiedUnits
    purchaseOrder { nexusRegistered lineItems { hardwareCategory productCode nexusRegistered } }
  }
}
"""


def test_the_mutation_registers_and_reports_what_it_tied(signed_in, db_session, project):
    _schedule_units(db_session, project, quantity=5)
    po, line = _mirrored_po(db_session, project=project, ordered=4, received=1)

    result = _execute(
        _MUTATION,
        {
            "input": {
                "poId": str(po.id),
                "lines": [
                    {
                        "poLineItemId": str(line.id),
                        "hardwareCategory": CATEGORY,
                        "productCode": CODE,
                        "tieQuantity": 3,
                    }
                ],
            }
        },
    )

    assert result.errors is None, result.errors
    payload = result.data["nexusRegisterPoLines"]
    assert payload["tiedUnits"] == 3
    assert payload["purchaseOrder"]["nexusRegistered"] is True
    assert payload["purchaseOrder"]["lineItems"] == [
        {"hardwareCategory": CATEGORY, "productCode": CODE, "nexusRegistered": True}
    ]
