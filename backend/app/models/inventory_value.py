"""INVENTORY VALUE: the door rows and the single cost that price them (#662).

Hardware already values itself - every inventory row and stock row carries a cost, or hangs off a PO
line that does. Doors do not: they are not received into Nexus at all, so nothing in the schema knows
how many are in the building or what one is worth. These two tables are that missing half, and they
are deliberately the only stored part of INVENTORY VALUE - the three figures the page shows are
computed on read from live inventory, so nothing here can drift out of agreement with the shelves.

DOORS ON HAND is one row per project plus one general row per company. The general row is the
project_id IS NULL row, and it is the doors that belong to no job - the stock/non-stock line. A
partial unique index enforces one of those per company, which a plain UNIQUE (company, project_id)
cannot: Postgres treats two NULLs as distinct, so the constraint alone would allow a second general
row per company and the page would silently double-count it.
"""

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import CheckConstraint, ForeignKey, Index, Integer, Numeric, String, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class DoorsOnHand(Base):
    """How many doors of one project (or none - the general row) are standing in the building."""

    __tablename__ = "doors_on_hand"
    __table_args__ = (
        UniqueConstraint("company", "project_id", name="uq_doors_on_hand_company_project"),
        Index(
            "uq_doors_on_hand_general_row",
            "company",
            unique=True,
            postgresql_where=text("project_id IS NULL"),
        ),
        CheckConstraint("quantity >= 0", name="ck_doors_on_hand_quantity_nonneg"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The GP company that owns the count - the tenant (#637). Carried here rather than inherited from
    # the project, because the general row has no project to inherit it from.
    company: Mapped[str] = mapped_column(String(15), nullable=False, index=True)
    # NULL is the company's general row: doors on hand that belong to no job.
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class InventoryValueSettings(Base):
    """AVERAGE DOOR COST: the one dollar figure every DOORS ON HAND row of a company is multiplied by.

    One row per company, keyed on the company itself rather than a surrogate id - there is nothing
    else to say about a company here, and the key being the company is what makes the get-or-create
    a single upsert-shaped read.
    """

    __tablename__ = "inventory_value_settings"

    company: Mapped[str] = mapped_column(String(15), primary_key=True)
    average_door_cost: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False, default=Decimal("0"), server_default="0"
    )
    updated_at: Mapped[datetime] = mapped_column(nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by: Mapped[str | None] = mapped_column(String, nullable=True)
