import os

import pytest
from alembic.config import Config

from alembic import command

# Tests build the demo from the made-up company, never from UBC (#1657), and a TestClient does not start
# the demo's nightly sync.
os.environ.setdefault("DEMO_SOURCE", "made-up")
os.environ.setdefault("DEMO_NIGHTLY_ENABLED", "false")


@pytest.fixture(autouse=True)
def _accounts_not_in_demo_mode(monkeypatch):
    """Every account a test makes up is out of demo mode (#1608) unless the test says otherwise.

    `tenant_scope` asks whether a scoped caller is in demo mode before anything else, and the answer is
    a Clerk read. The tests that stub an account's company stub `get_user_company` and nothing more, so
    without this every one of them would go to Clerk for the demo flag.

    The one read the request memos are filled from (`get_user_access`, #1894) is answered from the
    getters for its three keys, each looked up only when its key is read, so a test that stubs any one
    of them is answered by its stub and a key a test never reaches never asks Clerk."""
    from app.repositories import user_repository

    class _StubbedAccess:
        def __init__(self, user_id):
            self._user_id = user_id

        @property
        def roles(self):
            return user_repository.get_user_roles(self._user_id)

        @property
        def company(self):
            return user_repository.get_user_company(self._user_id)

        @property
        def demo_mode(self):
            return user_repository.get_user_demo_mode(self._user_id)

    monkeypatch.setattr(user_repository, "get_user_demo_mode", lambda user_id: False)
    monkeypatch.setattr(user_repository, "get_user_access", _StubbedAccess)


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
