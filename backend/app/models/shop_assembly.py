import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, Enum, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base
from .enums import AssemblyStatus, PullStatus, ShopAssemblyRequestStatus


class ShopAssemblyRequest(Base):
    __tablename__ = "shop_assembly_requests"
    __table_args__ = (Index("ix_shop_assembly_requests_project_status", "project_id", "status"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    request_number: Mapped[str] = mapped_column(String(50), nullable=False, unique=True)
    project_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[ShopAssemblyRequestStatus] = mapped_column(
        Enum(
            ShopAssemblyRequestStatus,
            name="shop_assembly_request_status",
            create_constraint=True,
        ),
        nullable=False,
    )
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    approved_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejected_by: Mapped[str | None] = mapped_column(String, nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    approved_at: Mapped[datetime | None] = mapped_column(nullable=True)
    rejected_at: Mapped[datetime | None] = mapped_column(nullable=True)

    openings: Mapped[list["ShopAssemblyOpening"]] = relationship(back_populates="shop_assembly_request")


class ShopAssemblyOpening(Base):
    __tablename__ = "shop_assembly_openings"
    __table_args__ = (
        Index(
            "ix_shop_assembly_openings_request",
            "shop_assembly_request_id",
        ),
        Index(
            "ix_shop_assembly_openings_opening_pull",
            "opening_id",
            "pull_status",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_request_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_requests.id"), nullable=False)
    opening_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("openings.id"), nullable=False)
    pull_status: Mapped[PullStatus] = mapped_column(
        Enum(PullStatus, name="pull_status", create_constraint=True),
        nullable=False,
    )
    assigned_to: Mapped[str | None] = mapped_column(String, nullable=True)
    assembly_status: Mapped[AssemblyStatus] = mapped_column(
        Enum(AssemblyStatus, name="assembly_status", create_constraint=True),
        nullable=False,
    )
    completed_at: Mapped[datetime | None] = mapped_column(nullable=True)

    shop_assembly_request: Mapped["ShopAssemblyRequest"] = relationship(back_populates="openings")
    items: Mapped[list["ShopAssemblyOpeningItem"]] = relationship(back_populates="shop_assembly_opening")


class ShopAssemblyOpeningItem(Base):
    __tablename__ = "shop_assembly_opening_items"
    __table_args__ = (
        Index(
            "ix_shop_assembly_opening_items_opening",
            "shop_assembly_opening_id",
        ),
        CheckConstraint("quantity >= 1", name="ck_shop_assembly_opening_items_quantity_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    shop_assembly_opening_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("shop_assembly_openings.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)

    shop_assembly_opening: Mapped["ShopAssemblyOpening"] = relationship(back_populates="items")
