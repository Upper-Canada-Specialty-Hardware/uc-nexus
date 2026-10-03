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
        # Tables without alembic_version can hold real data (a hand-dropped version table, a
        # partial restore), so the schema is never dropped on its own. Set ALLOW_SCHEMA_RESET=1
        # for one deploy to recover from a failed first migration.
        if os.environ.get('ALLOW_SCHEMA_RESET') != '1':
            print(
                'Refusing to start: the database has %d table(s) but no alembic_version table. '
                'Nothing was dropped. If this is a failed first migration, set ALLOW_SCHEMA_RESET=1 '
                'for one deploy to reset the schema; otherwise restore alembic_version.' % len(tables)
            )
            raise SystemExit(1)
        print('ALLOW_SCHEMA_RESET=1 and no alembic_version - resetting schema')
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
            # No tables at all, so only a failed first migration's enum types are dropped.
            print('Leftover enums with no tables - resetting schema')
            conn.execute(text('DROP SCHEMA public CASCADE'))
            conn.execute(text('CREATE SCHEMA public'))
            conn.commit()
        else:
            print('Fresh database')
    else:
        print('Existing database with migrations')
"

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
