from sqlalchemy import Boolean, Integer
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PackingSlipCounter(Base):
    """The next packing-slip sequence number - a single global row.

    Packing slip numbers used to be typed by hand on the confirm dialog, which handed the shipping
    user a uniqueness constraint to satisfy from memory. Nexus mints them now: a global PS-NNNNN
    sequence, so the number is unique across every project without anyone having to check.

    One row, forever. `is_singleton` is a constant-true primary key that makes a second row
    impossible - the same shape a global counter takes elsewhere - so the mint always locks and
    increments this exact row.

    Claimed with SELECT ... FOR UPDATE inside the confirming transaction, so two concurrent
    shipments serialize on it rather than racing to the same number, and a rolled-back confirm gives
    the number back instead of burning it.
    """

    __tablename__ = "packing_slip_counter"

    is_singleton: Mapped[bool] = mapped_column(Boolean, primary_key=True, default=True)
    # The value the NEXT packing slip takes.
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
