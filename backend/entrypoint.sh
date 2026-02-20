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

echo "Running database migrations..."
alembic upgrade head

echo "Starting server..."
exec uvicorn main:app --host 0.0.0.0 --port ${PORT:-8000}
