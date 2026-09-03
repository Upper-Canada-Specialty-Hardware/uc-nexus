"""Copy production's database into a preview environment's own Postgres, then neuter what would fire.

A Railway preview environment is a fork of production, and the fork's Postgres starts EMPTY. Every
previous attempt at making a preview useful worked by putting a little synthetic data in it - seeded
relay credentials, a stub relay serving a fixture - and every one of them drifted from what
production actually holds, which is the only thing worth testing a change against. This module
replaces all of it with the blunt version: on first boot the preview pg_dumps production and restores
it into itself, so a PR environment opens with production's data, production's relay_installs row
(the workstation relay authenticates to it with nothing seeded), and production's schema, which the
PR's own migrations then move forward.

GP is never cloned. GP is a live external system with one shared test company; there is nothing to
copy and nothing here touches it.

**The dangerous half is what a copied database would do on its own.** Production's rows describe
work that production is already doing. Restored into a preview that holds the SAME relay credential,
a queued GP write would drain a second time through the preview's channel and post a duplicate
receipt or a duplicate PO into real GP. So the restore is followed by a sanitize pass, in one
transaction, that cancels every gp_write_outbox row still on its way to GP. See
`NON_TERMINAL_OUTBOX_STATUSES` for what that means and why the terminal ones are left alone.

What is deliberately KEPT:

- `relay_events` - a ledger of things that already happened. Copying history re-fires nothing.
- `gp_write_idempotency` - these keys PREVENT a second GP write. Dropping them would remove the guard
  that stops a retried action from creating a PO production already created.
- `gp_po_sync_state` - the mirror's read watermark. The mirror only READS GP; a preserved cursor just
  saves the preview a full backfill it would otherwise redo.
- `relay_installs` - the entire point. The workstation relay's secret already matches this row.
"""

from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime

from sqlalchemy import text, update
from sqlalchemy.engine import URL, make_url

from app.config import DATABASE_URL, is_preview_environment, preview_clone_source_url
from app.models.gp_outbox import GpWriteOutbox

logger = logging.getLogger(__name__)

EXIT_OK = 0
EXIT_FAILED = 1
EXIT_NO_SOURCE = 2
EXIT_NOT_A_PREVIEW = 3

# The gp_write_outbox statuses a cloned row could still leave on: PENDING is waiting for the worker to
# claim it, and IN_FLIGHT means production's worker had claimed it at dump time - the preview's worker
# would find no owner and, on the next restart-driven requeue, send it. Both get cancelled.
#
# FAILED and CANCELLED are left exactly as they are. Neither drains on its own; both need an admin to
# press Retry, which puts the row back to PENDING - and since a CANCELLED row is just as retriable as
# a FAILED one (gp_outbox_repository.retry_entry accepts both), rewriting FAILED to CANCELLED would
# buy no protection at all while making the preview's queue page lie about what production holds.
NON_TERMINAL_OUTBOX_STATUSES = ("PENDING", "IN_FLIGHT")
CANCELLED_OUTBOX_STATUS = "CANCELLED"
OUTBOX_CANCEL_REASON = "cancelled by preview clone: queued on production"


class CloneError(RuntimeError):
    """The clone could not be completed. The message is what goes to stderr and fails the deploy."""


@dataclass
class CloneResult:
    """What the clone landed, for the deploy log and for /admin/reset-data's response body."""

    # The revision production's schema was on at dump time. `alembic upgrade head` runs after this and
    # moves it to the PR branch's head; logging it is what makes a divergent branch diagnosable.
    source_revision: str | None = None
    table_counts: dict[str, int] = field(default_factory=dict)
    outbox_cancelled: int = 0

    @property
    def total_rows(self) -> int:
        return sum(self.table_counts.values())


# --- pg_dump | pg_restore ------------------------------------------------------------------------


def _split_password(url: str) -> tuple[str, str | None]:
    """A libpq URI with the password removed, plus the password.

    The password goes to the child in PGPASSWORD rather than in the URI, because a URI on argv is
    readable by every process on the box through `ps` - and the one this carries is production's.

    Rebuilt rather than edited: `URL.set(password=None)` means "leave it alone", not "clear it". The
    driver suffix goes with it - a DATABASE_URL written `postgresql+psycopg2://` is a SQLAlchemy
    spelling that libpq does not understand."""
    parsed = make_url(url)
    sanitized = URL.create(
        drivername=parsed.drivername.split("+", 1)[0],
        username=parsed.username,
        host=parsed.host,
        port=parsed.port,
        database=parsed.database,
        query=parsed.query,
    )
    return sanitized.render_as_string(hide_password=False), parsed.password


def _tail(handle, limit: int = 2000) -> str:
    handle.seek(0)
    return handle.read().decode("utf-8", "replace")[-limit:].strip()


def _run_dump_restore(source_url: str, target_url: str) -> None:
    """Stream `pg_dump -Fc` straight into `pg_restore`. Raises CloneError if either side fails.

    Piped rather than staged through a file: production's dump is the whole application database and
    a preview container has no promise of disk for it. Both stderr streams go to temp files, not
    pipes - a pipe the parent is not draining while it waits on the other process is a deadlock, and
    pg_dump is chatty enough to fill one.

    `--clean --if-exists` on the restore is load-bearing, not tidiness. pg_restore exits NON-ZERO
    whenever it ignored any error at all, and a dump from PG 11 or newer carries the `public` schema
    as an object - so restoring into a target that already has an empty `public` (which every one of
    them does: the entrypoint's dirty-state check and /admin/reset-data both recreate it) fails on
    "schema public already exists" and a perfectly healthy clone reads as a failed one. `--clean`
    makes that a DROP-then-CREATE instead, and `--if-exists` keeps every DROP a no-op on the empty
    target. A dump that omits the schema object simply restores into the existing `public`.

    pg_restore's exit code is the only signal read after that. It still WARNs its way through every
    role and ACL the dump names that this cluster does not have, which is expected and harmless here
    (`--no-owner --no-privileges` is exactly the request to ignore them), so warnings are logged and
    not treated as failure."""
    source, source_password = _split_password(source_url)
    target, target_password = _split_password(target_url)

    dump_cmd = ["pg_dump", "-Fc", "--no-owner", "--no-privileges", source]
    restore_cmd = ["pg_restore", "--clean", "--if-exists", "--no-owner", "--no-privileges", "-d", target]

    dump_env = dict(os.environ)
    if source_password:
        dump_env["PGPASSWORD"] = source_password
    restore_env = dict(os.environ)
    if target_password:
        restore_env["PGPASSWORD"] = target_password

    with tempfile.TemporaryFile() as dump_err, tempfile.TemporaryFile() as restore_err:
        try:
            dump = subprocess.Popen(dump_cmd, stdout=subprocess.PIPE, stderr=dump_err, env=dump_env)
        except OSError as e:
            raise CloneError(f"could not start pg_dump: {e}") from e
        try:
            restore = subprocess.Popen(restore_cmd, stdin=dump.stdout, stderr=restore_err, env=restore_env)
        except OSError as e:
            # Closing our end makes pg_dump die on EPIPE rather than run the whole dump into nothing.
            dump.stdout.close()
            dump.wait()
            raise CloneError(f"could not start pg_restore: {e}") from e
        # The child owns the read end now; holding a copy here would keep the pipe open forever if
        # pg_restore exited early, and pg_dump would block writing into it.
        dump.stdout.close()

        restore_rc = restore.wait()
        dump_rc = dump.wait()

        if dump_rc != 0:
            raise CloneError(f"pg_dump of production failed (exit {dump_rc}): {_tail(dump_err)}")
        if restore_rc != 0:
            raise CloneError(f"pg_restore into this database failed (exit {restore_rc}): {_tail(restore_err)}")

        warnings = _tail(restore_err, 1000)
        if warnings:
            logger.info("pg_restore finished with warnings (roles and privileges are expected):\n%s", warnings)


# --- sanitize + inventory ------------------------------------------------------------------------


def sanitize_cloned_data(session) -> int:
    """Cancel every GP write the copy would otherwise send a second time. Returns the row count.

    One statement, inside the caller's transaction. Nothing else in the database re-fires an external
    effect on its own: notifications are in-app rows a bell reads, outbound email has no queue and no
    SMTP configured on a preview, the GP job and PO syncs only read, and the two ledgers
    (relay_events, gp_write_idempotency) are load-bearing history - see the module docstring."""
    result = session.execute(
        update(GpWriteOutbox)
        .where(GpWriteOutbox.status.in_(NON_TERMINAL_OUTBOX_STATUSES))
        .values(
            status=CANCELLED_OUTBOX_STATUS,
            last_error=OUTBOX_CANCEL_REASON,
            updated_at=datetime.utcnow(),
        )
    )
    return result.rowcount or 0


def read_alembic_revision(conn) -> str | None:
    """The revision stamped in the database, or None when there is no alembic_version table yet.

    The existence check is a separate statement because Postgres resolves relation names at parse
    time - a guard in the WHERE clause of the SELECT would not save it from erroring on a database
    that has never been migrated, which is precisely the case this has to answer for."""
    if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() is None:
        return None
    row = conn.execute(text("SELECT version_num FROM alembic_version LIMIT 1")).first()
    return row[0] if row else None


def table_row_counts(conn) -> dict[str, int]:
    """Row count per public table, for the deploy log. A count per table over a database this size is
    cheap next to the dump that just ran, and it is the only readable proof the clone landed."""
    names = [
        r[0]
        for r in conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' AND table_type = 'BASE TABLE' ORDER BY table_name"
            )
        ).all()
    ]
    counts: dict[str, int] = {}
    for name in names:
        quoted = '"' + name.replace('"', '""') + '"'
        counts[name] = conn.exec_driver_sql(f"SELECT count(*) FROM {quoted}").scalar() or 0
    return counts


# --- the clone -----------------------------------------------------------------------------------


def clone_production_into_this_database(source_url: str) -> CloneResult:
    """Dump `source_url` into this deployment's DATABASE_URL, sanitize, and report what landed.

    Callers that are not the CLI (POST /admin/reset-data) come in here directly - the environment
    checks and the exit codes belong to `main`, not to the work."""
    from app.database import SessionLocal, engine

    _run_dump_restore(source_url, DATABASE_URL)

    with SessionLocal() as session:
        cancelled = sanitize_cloned_data(session)
        session.commit()

    with engine.connect() as conn:
        result = CloneResult(
            source_revision=read_alembic_revision(conn),
            table_counts=table_row_counts(conn),
            outbox_cancelled=cancelled,
        )
    return result


def log_result(result: CloneResult) -> None:
    populated = {name: n for name, n in result.table_counts.items() if n}
    logger.info(
        "cloned production at alembic revision %s: %s rows across %s of %s tables",
        result.source_revision or "unknown",
        result.total_rows,
        len(populated),
        len(result.table_counts),
    )
    for name, count in sorted(populated.items(), key=lambda kv: (-kv[1], kv[0])):
        logger.info("  %-44s %s", name, count)
    logger.info("cancelled %s queued GP write(s) carried over from production", result.outbox_cancelled)


# --- the branch-behind-production message ---------------------------------------------------------


def migration_gap_message(revision: str | None) -> str:
    """The one line printed when `alembic upgrade head` cannot find the revision the clone landed on.

    That failure has exactly one cause worth naming: the copy came from production, production is
    ahead of this branch, and the branch's migration tree has no such revision. "Can't locate
    revision" on its own reads like a corrupt database, which sends people looking in the wrong
    place."""
    return (
        f"production's schema is at {revision or 'unknown'} and this branch does not have it: "
        "merge master into the branch"
    )


def print_migration_gap_message() -> int:
    from app.database import engine

    try:
        with engine.connect() as conn:
            revision = read_alembic_revision(conn)
    except Exception:
        revision = None
    print(migration_gap_message(revision))
    return EXIT_OK


# --- CLI ------------------------------------------------------------------------------------------


def main(argv: list[str] | None = None) -> int:
    """`python -m app.preview_clone`, run by entrypoint.sh before the migrations.

    Exit codes are the interface: 0 cloned, 1 failed (the deploy must go red - a preview that silently
    booted empty would be tested against nothing), 2 nothing configured to clone from (boot empty,
    which is where every environment stood before this existed), 3 not a preview."""
    logging.basicConfig(level=logging.INFO, format="%(message)s", stream=sys.stdout)
    parser = argparse.ArgumentParser(prog="preview_clone", description=__doc__)
    parser.add_argument(
        "--migration-gap-message",
        action="store_true",
        help="print the 'branch is behind production' line and exit; used by entrypoint.sh",
    )
    args = parser.parse_args(argv)

    if args.migration_gap_message:
        return print_migration_gap_message()

    if not is_preview_environment():
        print(
            "refusing to clone: this is not a Railway preview environment, and the clone OVERWRITES "
            "the database it runs against",
            file=sys.stderr,
        )
        return EXIT_NOT_A_PREVIEW

    source_url = preview_clone_source_url()
    if source_url is None:
        logger.warning(
            "no clone source configured; booting empty. Set PREVIEW_CLONE_PASSWORD and the PG_DIRECT_* "
            "coordinates on PRODUCTION so forks inherit them."
        )
        return EXIT_NO_SOURCE

    try:
        result = clone_production_into_this_database(source_url)
    except CloneError as e:
        print(str(e), file=sys.stderr)
        return EXIT_FAILED
    except Exception as e:  # noqa: BLE001 - the exit code is the contract; the reason goes to stderr
        print(f"clone failed: {e}", file=sys.stderr)
        return EXIT_FAILED

    log_result(result)
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
