import uuid
from datetime import datetime

from sqlalchemy import DateTime, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class RelayInstall(Base):
    """One on-prem relay install (one workstation). The relay generates its own long-lived Bearer
    secret and registers it here via the one-time enrollment token (the backend can't reach the relay,
    but the relay can reach the backend), then presents that same secret on its outbound WS connect
    handshake (see relay_repository.authenticate_secret).

    A credential and a label, nothing more. Which GP companies the install serves is GP's answer, not
    one kept here: the relay discovers it from GP's company master and reports it on the hello
    frame, so the gateway holds it for the life of the connection."""

    __tablename__ = "relay_installs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    label: Mapped[str] = mapped_column(String, nullable=False)
    hostname: Mapped[str | None] = mapped_column(String, nullable=True)  # filled by the relay at enrollment
    # SHA-256 hex of the relay's long-lived Bearer secret - the sole credential for any install
    # enrolled or adopted from migration 067 on. Indexed so a handshake is a single row fetch rather
    # than a scan. NULL until the relay enrolls.
    secret_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    # LEGACY: the same secret Fernet-encrypted, for rows that predate 067. authenticate_secret upgrades
    # such a row to secret_hash (and NULLs this) on its next handshake; nothing writes it any more.
    secret_encrypted: Mapped[str | None] = mapped_column(Text, nullable=True)
    # one-time enrollment token: only the SHA-256 hash is stored (it's a credential, shown once at provision).
    enrollment_token_hash: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    enrollment_token_expires_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    enrolled_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_seen_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Durable audit of an admin-armed adopt window being used against this install (#353 PR B).
    # Adoption rebinds the credential from an unauthenticated connection, so "was this install ever
    # adopted, by whom, when" has to survive on the row - the window itself is in-memory and gone on
    # the next deploy. Rendered in the admin grid.
    adopted_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    adopted_by: Mapped[str | None] = mapped_column(String, nullable=True)  # Clerk user id of the arming admin
