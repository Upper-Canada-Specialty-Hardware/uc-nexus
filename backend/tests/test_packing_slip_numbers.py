"""Server-minted packing slip numbers.

The number is a global PS-NNNNN sequence Nexus owns, minted inside the confirming transaction. Three
properties are worth pinning: it advances by one each mint, it skips a value a legacy hand-typed slip
already occupies, and a rolled-back mint gives the number back rather than burning it.
"""

import re
import uuid
from datetime import datetime

from sqlalchemy import select

from app.models.enums import ShipmentStatus
from app.models.packing_slip_counter import PackingSlipCounter
from app.models.project import Project
from app.models.shipping import PackingSlip
from app.repositories.packing_slip_numbers import mint_packing_slip_number


def _next_value(session) -> int:
    return session.scalars(select(PackingSlipCounter.next_value)).one()


def _project(session) -> Project:
    p = Project(id=uuid.uuid4(), project_id=f"PROJ-{uuid.uuid4().hex[:8]}", description="Test")
    session.add(p)
    session.flush()
    return p


def test_the_sequence_advances_by_one_each_mint(db_session):
    first = mint_packing_slip_number(db_session)
    second = mint_packing_slip_number(db_session)
    assert re.fullmatch(r"PS-\d{5}", first)
    assert re.fullmatch(r"PS-\d{5}", second)
    assert int(second[3:]) == int(first[3:]) + 1


def test_a_legacy_hand_typed_slip_holding_the_next_value_is_skipped(db_session):
    """Existing slips keep their numbers, so a hand-typed slip sitting on the value the counter is
    about to hand out is walked past rather than collided with."""
    project = _project(db_session)
    taken = f"PS-{_next_value(db_session):05d}"
    db_session.add(
        PackingSlip(
            id=uuid.uuid4(),
            packing_slip_number=taken,
            project_id=project.id,
            shipped_by="legacy",
            shipped_at=datetime.utcnow(),
            status=ShipmentStatus.SCHEDULED,
        )
    )
    db_session.flush()

    minted = mint_packing_slip_number(db_session)
    assert minted != taken
    assert int(minted[3:]) == int(taken[3:]) + 1


def test_a_rolled_back_mint_returns_the_number(db_session):
    """The counter claim lives in the same transaction as the slip, so a rollback gives the number
    back instead of skipping it - the same atomicity story as the request-number counter (#493)."""
    savepoint = db_session.begin_nested()
    first = mint_packing_slip_number(db_session)
    savepoint.rollback()

    second = mint_packing_slip_number(db_session)
    assert second == first
