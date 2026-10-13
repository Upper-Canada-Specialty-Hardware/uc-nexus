import os

import pytest
from alembic.config import Config

from alembic import command


@pytest.fixture(autouse=True)
def _accounts_not_in_demo_mode(monkeypatch):
    """Every account a test makes up is out of demo mode (#1608) unless the test says otherwise.

    `tenant_scope` asks whether a scoped caller is in demo mode before anything else, and the answer is
    a Clerk read. The tests that stub an account's company stub `get_user_company` and nothing more, so
    without this every one of them would go to Clerk for the demo flag."""
    from app.repositories import user_repository

    monkeypatch.setattr(user_repository, "get_user_demo_mode", lambda user_id: False)


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
