import uuid
from datetime import datetime

from sqlalchemy import Column, ForeignKey, String, Table, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .project import Project

# M2M: the projects a buyer may create POs for (issue #216).
buyer_assignment_projects = Table(
    "buyer_assignment_projects",
    Base.metadata,
    Column("buyer_assignment_id", ForeignKey("buyer_assignments.id", ondelete="CASCADE"), primary_key=True),
    Column("project_id", ForeignKey("projects.id", ondelete="CASCADE"), primary_key=True),
)


class BuyerAssignment(Base):
    """Issue #216: per-GP-buyer authorization - which projects a buyer creates POs for. STRICT: a
    buyer with no row, or a project outside their assignment, cannot create a project PO. buyer_id is
    the GP BUYERID (char 15); a UC Nexus account is linked to it via the user's Clerk
    publicMetadata.gpBuyerId (set in Admin -> User Management).

    Per-buyer *cost-code* designation was removed: it restricted each buyer to a hand-maintained
    subset of a job's cost codes, which silently hid valid codes from the register-PO dropdown. Any
    cost code GP reports active for the job (JC00701 WS_Inactive = 0) is now selectable.
    """

    __tablename__ = "buyer_assignments"
    __table_args__ = (UniqueConstraint("buyer_id", name="uq_buyer_assignments_buyer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[str] = mapped_column(String(15), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects: Mapped[list[Project]] = relationship(secondary=buyer_assignment_projects)
