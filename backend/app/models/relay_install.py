import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class RelayInstall(Base):
    """One on-prem relay install (one workstation). The relay generates its own long-lived Bearer
    secret and registers it here via the one-time enrollment token (the backend can't reach the relay,
    but the relay can reach the backend), then presents that same secret on its outbound WS connect
    handshake (see relay_repository.authenticate_secret)."""

    __tablename__ = "relay_installs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String, nullable=False)
    company: Mapped[str] = mapped_column(String, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)  # filled by the relay at enrollment
    # long-lived relay Bearer secret, Fernet-encrypted at rest. NULL until the relay enrolls.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # one-time enrollment token: only the SHA-256 hash is stored (it's a credential, shown once at provision).
    enrollment_token_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    enrollment_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
