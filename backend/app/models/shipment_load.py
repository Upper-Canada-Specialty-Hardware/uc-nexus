import uuid
from datetime import date, datetime
from typing import TYPE_CHECKING

from sqlalchemy import Date, ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base

if TYPE_CHECKING:
    from .project import Project
    from .shipping import PackingSlip


class ShipmentLoad(Base):
    """One truck trip: the packing slips that leave the dock together (#1720).

    A packing slip is one project's shipment, and the floor never talked about those - it talked about
    "Thursday's shipment", which might be two projects' slips on the same truck. The load is that
    thing, named so it can be said out loud: the lead project's number and the ship date, as the
    outbound supervisor asked for it (`22713-10152026`), with `-2` when the same project leads a second
    load that day. It sits above the slips in the drill-down: load, slip, container, line.

    A load has no status of its own. Where it is comes from its slips, and it can be joined only while
    none of them has been picked up (see `shipment_loads.joinable_loads`).

    `company` is the GP company of every slip on it, and what scopes it: a truck never carries two
    companies' paperwork, and demo reset finds a demo load by this column.
    """

    __tablename__ = "shipment_loads"
    __table_args__ = (Index("ix_shipment_loads_company_ship_date", "company", "ship_date"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    load_number: Mapped[str] = mapped_column(String(60), nullable=False, unique=True)
    company: Mapped[str] = mapped_column(String(15), nullable=False)
    # The project whose number names the load, and the day it names. Both are fixed when the load is
    # started: a number people have already said on the phone must not change under them when the
    # pickup date on a slip is corrected.
    lead_project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    ship_date: Mapped[date] = mapped_column(Date, nullable=False)
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    slips: Mapped[list["PackingSlip"]] = relationship(
        "PackingSlip", back_populates="load", order_by="PackingSlip.shipped_at"
    )
    lead_project: Mapped["Project"] = relationship(viewonly=True)
