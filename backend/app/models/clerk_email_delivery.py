from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, String
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class ClerkEmailDelivery(Base):
    """One row per Clerk email Nexus has sent (#1690), so a retried webhook never mails it twice.

    ucsh-mailer's own idempotency key only lasts ten minutes and a restart forgets it, while Clerk keeps
    retrying a failed webhook for hours. The row is written in the same transaction as the send and
    holds nothing but Clerk's opaque id, the route and the time: no recipient, subject, body or code."""

    __tablename__ = "clerk_email_deliveries"
    __table_args__ = (CheckConstraint("route IN ('mailer', 'smtp2go')", name="ck_clerk_email_deliveries_route"),)

    clerk_email_id: Mapped[str] = mapped_column(String(255), primary_key=True)
    # 'mailer' (ucsh-mailer, inside the company) or 'smtp2go' (everyone else).
    route: Mapped[str] = mapped_column(String(16), nullable=False)
    sent_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
