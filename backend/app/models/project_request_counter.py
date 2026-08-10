import uuid

from sqlalchemy import ForeignKey, Integer
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ProjectRequestCounter(Base):
    """The next pull-request sequence number for a project (#493).

    Request numbers used to be typed by hand on the shop-assembly and shipping-out wizard steps,
    which made them a uniqueness constraint the user had to satisfy from memory - two people
    raising requests on the same project at once collided, and nothing tied a number to its job.

    One counter per project, spanning BOTH request types. A shop-assembly request and a
    shipping-out request both become warehouse pulls, and one chronological sequence per project is
    what a warehouse user can actually reason about; two independent sequences would put a 23093-004
    on the rack next to a different 23093-004.

    Claimed with SELECT ... FOR UPDATE inside the creating transaction, so two concurrent creates
    serialize on this row rather than racing to the same number.
    """

    __tablename__ = "project_request_counters"

    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), primary_key=True)
    # The value the NEXT request on this project takes.
    next_value: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
