from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class CompanyLetterhead(Base):
    """What a GP company prints as itself on the documents Nexus makes (#1689).

    One row per company code. `gp_name` is GP's own company name, kept from the last relay hello that
    reported it, so a document printed while the relay is down still names the company rather than its
    code. `address` is the company's printed address, typed per company by a PO manager; a company with
    none yet prints the shared PO document settings' from-address below its name line.
    """

    __tablename__ = "company_letterheads"

    company: Mapped[str] = mapped_column(String(15), primary_key=True)
    gp_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    gp_name_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # The address lines under the name, one per line. The name is never typed here: it is GP's.
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    address_updated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
