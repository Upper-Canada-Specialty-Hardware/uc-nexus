import uuid
from datetime import datetime

from sqlalchemy import String, Integer, Index, ForeignKey
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[str] = mapped_column(String, nullable=False, index=True)
    description: Mapped[str | None] = mapped_column(String, nullable=True)
    job_site_name: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(String, nullable=True)
    city: Mapped[str | None] = mapped_column(String, nullable=True)
    state: Mapped[str | None] = mapped_column(String, nullable=True)
    zip: Mapped[str | None] = mapped_column(String, nullable=True)
    contractor: Mapped[str | None] = mapped_column(String, nullable=True)
    project_manager: Mapped[str | None] = mapped_column(String, nullable=True)
    application: Mapped[str | None] = mapped_column(String, nullable=True)
    submittal_job_no: Mapped[str | None] = mapped_column(String, nullable=True)
    submittal_assignment_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    estimator_code: Mapped[str | None] = mapped_column(String, nullable=True)
    titan_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    openings: Mapped[list["Opening"]] = relationship(back_populates="project")


class Opening(Base):
    __tablename__ = "openings"
    __table_args__ = (
        Index("ix_openings_project_opening", "project_id", "opening_number"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("projects.id"), nullable=False
    )
    opening_number: Mapped[str] = mapped_column(String, nullable=False, index=True)
    building: Mapped[str | None] = mapped_column(String, nullable=True)
    floor: Mapped[str | None] = mapped_column(String, nullable=True)
    location: Mapped[str | None] = mapped_column(String, nullable=True)
    location_to: Mapped[str | None] = mapped_column(String, nullable=True)
    location_from: Mapped[str | None] = mapped_column(String, nullable=True)
    hand: Mapped[str | None] = mapped_column(String, nullable=True)
    width: Mapped[str | None] = mapped_column(String, nullable=True)
    length: Mapped[str | None] = mapped_column(String, nullable=True)
    door_thickness: Mapped[str | None] = mapped_column(String, nullable=True)
    jamb_thickness: Mapped[str | None] = mapped_column(String, nullable=True)
    door_type: Mapped[str | None] = mapped_column(String, nullable=True)
    frame_type: Mapped[str | None] = mapped_column(String, nullable=True)
    interior_exterior: Mapped[str | None] = mapped_column(String, nullable=True)
    keying: Mapped[str | None] = mapped_column(String, nullable=True)
    heading_no: Mapped[str | None] = mapped_column(String, nullable=True)
    single_pair: Mapped[str | None] = mapped_column(String, nullable=True)
    assignment_multiplier: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    project: Mapped["Project"] = relationship(back_populates="openings")
