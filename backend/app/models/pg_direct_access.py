import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column

from . import Base


class PgDirectAccess(Base):
    """Registry of minted direct-Postgres logins (db-admin-postgres-access).

    One row per grant of a personal `nexus_rw` login over the public proxy. It backs the Database
    Access grid, ties each login to a Clerk user, and is the allowlist the repository guardrails check
    - a rotate/revoke target absent from here is refused, and mint's tolerant pre-sweep only ever
    fires on a role the registry says should not exist.

    The two partial uniques (`WHERE revoked_at IS NULL`) make "one live grant per user" and "one live
    role name" database invariants rather than app conventions, while still allowing a revoked user to
    be re-minted: the same deterministic role name lands on a NEW row, and the old, closed row keeps
    the history. `db_role` is not globally unique for exactly that reason.
    """

    __tablename__ = "pg_direct_access"
    __table_args__ = (
        Index(
            "uq_pg_direct_access_live_user",
            "clerk_user_id",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
        Index(
            "uq_pg_direct_access_live_role",
            "db_role",
            unique=True,
            postgresql_where=text("revoked_at IS NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # The Postgres role name, deterministic from the Clerk user id. 63 is Postgres' identifier limit.
    db_role: Mapped[str] = mapped_column(String(63), nullable=False)
    clerk_user_id: Mapped[str] = mapped_column(String, nullable=False)
    # Clerk user id of the DB Admin who minted this grant.
    created_by: Mapped[str] = mapped_column(String, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    last_rotated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Set when the login is revoked; NULL means live. The partial uniques above and every guardrail
    # key off this column.
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class PgDirectAccessAudit(Base):
    """Append-only record of who minted / rotated / revoked which direct-Postgres login, and when.

    Separate from the DB-level `session_user` attribution the per-user logins give you at query time:
    that says who ran a SQL statement, this says who handed out (or took away) the credential. Backs
    the history panel under the Database Access grid.

    `action` is a plain string with a CHECK constraint rather than a DB enum, which keeps the two
    enum files (models/enums.py + schemas/enums.py) out of it for a fixed three-value set.
    """

    __tablename__ = "pg_direct_access_audit"
    __table_args__ = (
        CheckConstraint(
            "action IN ('MINT', 'ROTATE', 'REVOKE')",
            name="ck_pg_direct_access_audit_action",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # Clerk user id of the DB Admin who performed the action.
    actor_clerk_id: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    db_role: Mapped[str] = mapped_column(String(63), nullable=False)
    # Clerk user id the login belongs to. Nullable so a revoke can still be recorded for a role whose
    # registry mapping is already gone (a dev cluster recreated out from under the registry).
    target_clerk_id: Mapped[str | None] = mapped_column(String, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
