"""Two people defining the same shelf at once get a conflict, not a server error (#1387).

The duplicate read in create_warehouse_location is unlocked, so both racing requests can pass it. The
pre-check is hidden here, as it is for the second of two racing requests; the unique key then refuses
the insert, which must surface as the usual conflict with the transaction still usable.
"""

import pytest

from app.errors import ConflictError
from app.repositories import warehouse as warehouse_repository

from .inventory_fixtures import define_location, wh_id


def test_a_racing_duplicate_definition_is_a_conflict_not_a_server_error(db_session, monkeypatch):
    define_location(db_session, aisle="R1", row="1", bay="1")

    real_scalars = db_session.scalars
    calls = {"n": 0}

    class _NothingFound:
        def first(self):
            return None

    def blind_first_read(*args, **kwargs):
        calls["n"] += 1
        return _NothingFound() if calls["n"] == 1 else real_scalars(*args, **kwargs)

    monkeypatch.setattr(db_session, "scalars", blind_first_read)

    with pytest.raises(ConflictError):
        warehouse_repository.create_warehouse_location(db_session, wh_id(db_session), "R1", "1", "1")

    monkeypatch.setattr(db_session, "scalars", real_scalars)
    # The savepoint rolled back only the failed insert; the outer transaction carries on.
    assert define_location(db_session, aisle="R2", row="1", bay="1").aisle == "R2"
