import uuid
from datetime import datetime

from sqlalchemy import Enum, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import Classification


class ProjectProductClassification(Base):
    """A project's list of product classifications, kept apart from any hardware schedule (#1443).

    The product owner ruled that a product's UCH Shop / UCH Site belongs to the project, not to whichever
    schedule was imported last. A newer schedule appends the products it brings in and never changes one
    already listed - that is done on the project's Hardware Classifications page - and a product a newer
    schedule dropped stays listed, so Nexus remembers it exists. hardware_items.classification is kept in
    step with this list. By Others is not listed here: it stays a project_excluded_items row.
    """

    __tablename__ = "project_product_classifications"
    __table_args__ = (
        UniqueConstraint("project_id", "hardware_category", "product_code", name="uq_project_product_classifications"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    classification: Mapped[Classification] = mapped_column(
        Enum(Classification, name="classification", create_constraint=True),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    # Who last set it: whoever changed it on the page, or whoever finalized the import that first listed it.
    # Null for a row the migration backfilled from the schedule rows.
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
