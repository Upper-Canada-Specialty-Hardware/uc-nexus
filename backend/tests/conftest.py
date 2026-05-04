import os

import pytest
from alembic.config import Config

from alembic import command


@pytest.fixture(scope="session")
def _migrate_database():
    if not os.getenv("DATABASE_URL"):
        pytest.skip("DATABASE_URL not set; skipping DB-backed tests")
    cfg = Config("alembic.ini")
    command.upgrade(cfg, "head")


@pytest.fixture
def db_session(_migrate_database):
    from app.database import SessionLocal, engine

    connection = engine.connect()
    transaction = connection.begin()
    session = SessionLocal(bind=connection)
    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
