import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base
from .enums import ShipmentPhotoKind


class ShipmentPhoto(Base):
    """A photo of a shipment (#1728): a container as it was loaded, or the load at the site.

    The floor already photographs every container before it goes on a truck and files the pictures by
    hand; this keeps them on the shipment, where a discrepancy is investigated. A loading photo hangs
    off its container (taken while it is still being built, so before any slip exists); a delivery
    photo hangs off the slip. `project_id` is always set, so tenancy and demo reset reach every photo
    the same way whichever it hangs off.

    The image itself is in object storage under `s3_key`; the row is what makes it findable.
    """

    __tablename__ = "shipment_photos"
    __table_args__ = (
        Index("ix_shipment_photos_container", "container_id"),
        Index("ix_shipment_photos_packing_slip", "packing_slip_id"),
        CheckConstraint(
            "container_id IS NOT NULL OR packing_slip_id IS NOT NULL", name="ck_shipment_photos_has_subject"
        ),
        CheckConstraint("file_size >= 1", name="ck_shipment_photos_file_size_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    container_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("shipment_containers.id", ondelete="CASCADE"), nullable=True
    )
    packing_slip_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("packing_slips.id"), nullable=True)
    kind: Mapped[ShipmentPhotoKind] = mapped_column(
        Enum(ShipmentPhotoKind, name="shipment_photo_kind", create_constraint=True), nullable=False
    )
    s3_key: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    content_type: Mapped[str] = mapped_column(String, nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    taken_by: Mapped[str] = mapped_column(String, nullable=False)
    taken_by_user_id: Mapped[str | None] = mapped_column(String, nullable=True)
    taken_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
