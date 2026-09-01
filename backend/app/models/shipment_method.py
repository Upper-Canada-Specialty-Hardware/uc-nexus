import uuid
from datetime import datetime

from sqlalchemy import Boolean, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ShipmentMethod(Base):
    """How a shipment travels: the shipping department's own list of carriers and services (#451).

    A managed list rather than free text on the slip, because the same handful of answers come back
    every time - "our truck", a named courier, customer pickup - and free text spells them five ways
    across a year of shipments. It is deliberately NOT a GP entity: nothing downstream consumes it,
    it is documentation of how a load left the building.

    Retiring one is `is_active = False`, not a delete. A method that carried shipments last year
    still has to be readable on those shipments, and the dropdown only offers active ones. `name` is
    unique so the list cannot grow two spellings of the same carrier, which is the whole point.

    Note what does NOT reference this table: `packing_slips.shipment_method` is a plain string
    snapshot, taken at confirm time, exactly like `pickup_location` beside it. A shipment printed a
    year later has to say what the driver was told, and a method that has since been renamed or
    deleted must not be able to change or erase that.
    """

    __tablename__ = "shipment_methods"
    # Unique per company (#637): the list is one shipping department's own, so two tenants both
    # running "Our truck" is two rows, not a collision.
    __table_args__ = (UniqueConstraint("company", "name", name="uq_shipment_methods_company_name"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The GP company that owns this method - the tenant (#637).
    company: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Where it sits in the dropdown. The shipping department's most-used method should be first, and
    # alphabetical is not that order.
    sort_order: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
