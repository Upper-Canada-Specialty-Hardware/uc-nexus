#!/bin/bash
set -e

echo "Checking database state..."
python -c "
from sqlalchemy import create_engine, text, inspect
import os
engine = create_engine(os.environ['DATABASE_URL'])
with engine.connect() as conn:
    inspector = inspect(conn)
    tables = inspector.get_table_names()
    has_version = 'alembic_version' in tables
    if not has_version and tables:
        print('Dirty state from failed migration - resetting schema')
        conn.execute(text('DROP SCHEMA public CASCADE'))
        conn.execute(text('CREATE SCHEMA public'))
        conn.commit()
    elif not has_version:
        # Check for leftover enum types without tables
        result = conn.execute(text(
            \"SELECT 1 FROM pg_type WHERE typtype = 'e' \"
            \"AND typnamespace = (SELECT oid FROM pg_namespace WHERE nspname = 'public') LIMIT 1\"
        ))
        if result.fetchone():
            print('Leftover enums detected - resetting schema')
            conn.execute(text('DROP SCHEMA public CASCADE'))
            conn.execute(text('CREATE SCHEMA public'))
            conn.commit()
        else:
            print('Fresh database')
    else:
        print('Existing database with migrations')
"

# A Railway preview environment (uc-nexus-pr-<N>) is a fork of production whose Postgres starts
# EMPTY. On that first boot only - no alembic_version means nothing has ever populated this database -
# take a copy of production's, so the PR is tested against real data and the workstation relay's
# credential already matches a row here. See app/preview_clone.py.
IS_PREVIEW=0
if [[ "${RAILWAY_ENVIRONMENT_NAME:-}" =~ ^uc-nexus-pr-[0-9]+$ ]]; then
    IS_PREVIEW=1
fi

HAS_VERSION=$(python - <<'PY'
import os

from sqlalchemy import create_engine, text

engine = create_engine(os.environ["DATABASE_URL"])
with engine.connect() as conn:
    print("yes" if conn.execute(text("SELECT to_regclass('public.alembic_version')")).scalar() else "no")
PY
)

if [ "$IS_PREVIEW" = "1" ] && [ "$HAS_VERSION" = "no" ]; then
    echo "Preview environment with an empty database - cloning production..."
    set +e
    python -m app.preview_clone
    CLONE_RC=$?
    set -e
    if [ "$CLONE_RC" = "2" ]; then
        echo "No clone source configured - continuing with an empty database."
    elif [ "$CLONE_RC" != "0" ]; then
        # Deliberately fatal. A preview that quietly booted empty looks healthy and is worth nothing:
        # every test run against it would be testing a change against no data.
        echo "Clone failed (exit $CLONE_RC) - refusing to start." >&2
        exit 1
    fi
fi

echo "Running database migrations..."
set +e
alembic upgrade head 2>&1 | tee /tmp/alembic-upgrade.log
MIGRATE_RC=${PIPESTATUS[0]}
set -e
if [ "$MIGRATE_RC" != "0" ]; then
    # The one failure a cloned preview has that production does not: the copy carries production's
    # revision, and a branch cut before that revision has no such node in its migration tree. Alembic
    # reports it as "Can't locate revision", which reads like a corrupt database.
    if [ "$IS_PREVIEW" = "1" ] && grep -q "Can't locate revision" /tmp/alembic-upgrade.log; then
        python -m app.preview_clone --migration-gap-message
    fi
    exit 1
fi

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
