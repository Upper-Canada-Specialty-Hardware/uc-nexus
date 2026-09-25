import uuid
from datetime import datetime

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class HardwareClassificationChange(Base):
    """One manual override of a product's classification after import (#735).

    `from_choice` / `to_choice` are HardwareClassificationChoice values, plus UNCLASSIFIED and MIXED
    on the from side, held as text so the log reads as written even if the choices are renamed later.
    """

    __tablename__ = "hardware_classification_changes"
    __table_args__ = (Index("ix_hardware_classification_changes_project", "project_id", "changed_at"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    from_choice: Mapped[str] = mapped_column(String(20), nullable=False)
    to_choice: Mapped[str] = mapped_column(String(20), nullable=False)
    changed_by: Mapped[str] = mapped_column(String, nullable=False)
    changed_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
