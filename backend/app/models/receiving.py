import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from . import Base


class ReceiveRecord(Base):
    __tablename__ = "receive_records"
    __table_args__ = (Index("ix_receive_records_po_id", "po_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    po_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("purchase_orders.id"), nullable=False)
    received_at: Mapped[datetime] = mapped_column(nullable=False)
    received_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    line_items: Mapped[list["ReceiveLineItem"]] = relationship(back_populates="receive_record")


class ReceiveLineItem(Base):
    __tablename__ = "receive_line_items"
    __table_args__ = (
        Index("ix_receive_line_items_receive_record", "receive_record_id"),
        Index("ix_receive_line_items_po_line_item", "po_line_item_id"),
        CheckConstraint("quantity_received >= 1", name="ck_receive_line_items_quantity_received_positive"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    receive_record_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("receive_records.id"), nullable=False)
    po_line_item_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("po_line_items.id"), nullable=False)
    hardware_category: Mapped[str] = mapped_column(String, nullable=False)
    product_code: Mapped[str] = mapped_column(String, nullable=False)
    quantity_received: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)

    receive_record: Mapped["ReceiveRecord"] = relationship(back_populates="line_items")
