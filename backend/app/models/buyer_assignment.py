import uuid
from datetime import datetime

from sqlalchemy import JSON, Column, ForeignKey, String, Table, UniqueConstraint
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
    """Issue #216: per-GP-buyer authorization - which projects a buyer creates POs for and which GP
    cost codes they may use. STRICT: a buyer with no row (or a project/cost code outside their
    assignment) cannot create a project PO. buyer_id is the GP BUYERID (char 15); a UC Nexus account
    is linked to it via the user's Clerk publicMetadata.gpBuyerId (set in Admin -> User Management).
    """

    __tablename__ = "buyer_assignments"
    __table_args__ = (UniqueConstraint("buyer_id", name="uq_buyer_assignments_buyer_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    buyer_id: Mapped[str] = mapped_column(String(15), nullable=False)
    # Designated GP cost codes as 'cc1-cc2' strings (e.g. '310-000'); the dialog offers only the
    # job's live cost codes whose code part matches one of these.
    cost_codes: Mapped[list] = mapped_column(JSON, nullable=False, default=list)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    projects: Mapped[list[Project]] = relationship(secondary=buyer_assignment_projects)
