"""Server-minted packing-slip numbers.

Packing slip numbers used to be typed by hand on the confirm dialog. That handed the shipping user a
uniqueness constraint to satisfy from memory, and nothing tied a number to a shape. Nexus mints them
now: a single global sequence formatted PS-NNNNN, minted inside the confirming transaction so a
rolled-back confirm gives the number back rather than burning it - the same atomicity story as
request_numbers.py (#493).

Legacy user-typed slips keep whatever numbers they already hold. The mint skips any value a legacy
slip already occupies (the uniqueness guard in confirm_shipment stays as the backstop), so a
hand-typed "PS-00007" from before this change never collides with the sequence catching up to it.
"""

from sqlalchemy import BigInteger, cast, func, select
from sqlalchemy.orm import Session

from app.demo import is_demo_company
from app.models.packing_slip_counter import PackingSlipCounter
from app.models.shipping import PackingSlip

# Key for the transaction-scoped advisory lock the demo company's own sequence is minted under.
_DEMO_PACKING_SLIP_LOCK_KEY = 1_608_001


def _mint_demo_packing_slip_number(session: Session) -> str:
    """The demo company's next slip number, PS-DNNNNN (#1608). Its own sequence, read off the demo
    slips themselves, so a demo shipment never takes a value from the real counter and a reset that
    deletes the demo slips starts the demo numbers over."""
    session.execute(select(func.pg_advisory_xact_lock(_DEMO_PACKING_SLIP_LOCK_KEY)))
    suffix = func.substring(PackingSlip.packing_slip_number, r"^PS-D([0-9]+)$")
    max_seq = session.scalar(select(func.max(cast(suffix, BigInteger))).where(suffix.is_not(None)))
    return f"PS-D{(max_seq or 0) + 1:05d}"


def mint_packing_slip_number(session: Session, company: str | None = None) -> str:
    """Claim the next packing-slip number.

    The singleton counter row is locked FOR UPDATE, so two concurrent confirms serialize here rather
    than racing to the same number. The lock is held until the caller's transaction commits, which is
    what makes the number and the slip it names atomic.

    Each claimed value is checked against existing slip numbers: a hand-typed slip from before the
    server owned the sequence may sit on a value the counter is about to hand out, and the mint walks
    past any such collision to the next free number, advancing the counter as it goes.

    The demo company (#1608) mints from its own sequence and leaves the counter alone.
    """
    if is_demo_company(company):
        return _mint_demo_packing_slip_number(session)
    counter = session.scalars(select(PackingSlipCounter).with_for_update()).first()
    if counter is None:
        # Only reachable if the seed row is missing (a database built before the migration seeded it).
        # Insert-then-lock: the constant-true primary key makes a concurrent duplicate impossible.
        counter = PackingSlipCounter(is_singleton=True, next_value=1)
        session.add(counter)
        session.flush()

    while True:
        seq = counter.next_value
        counter.next_value = seq + 1
        candidate = f"PS-{seq:05d}"
        taken = session.scalars(select(PackingSlip.id).where(PackingSlip.packing_slip_number == candidate)).first()
        if taken is None:
            session.flush()
            return candidate
