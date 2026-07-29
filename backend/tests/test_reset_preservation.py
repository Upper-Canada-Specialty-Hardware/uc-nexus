"""Column derivation for the tables that survive /admin/reset-data (#410, #411).

The bug being locked down is a silent one. The reset used to name all 13 `relay_installs` columns by
hand, twice, in raw SQL - so a migration that added a column left it NULL on every preserved row after
the next reset, with nothing failing and nothing logged. The fix is that the column list comes off the
model, and these tests assert it stays that way.

All pure string/metadata work, so they need no Postgres and run in the local suite as well as CI.
"""

import pytest
from sqlalchemy import inspect as sa_inspect

from app.models.buyer_assignment import BuyerAssignment
from app.models.project import Project
from app.models.relay_install import RelayInstall
from app.services.reset_preservation import PRESERVED_MODELS, preserved_columns, snapshot_statement


def _all_columns(model) -> list[str]:
    return [c.name for c in model.__table__.columns]


@pytest.mark.parametrize("model", PRESERVED_MODELS, ids=lambda m: m.__tablename__)
def test_every_model_column_is_preserved_when_the_table_is_current(model):
    """The everyday case: live table matches the model, so nothing is left behind."""
    assert preserved_columns(model, _all_columns(model)) == _all_columns(model)


def test_selects_every_relay_install_column():
    """#411 exactly: the generated SELECT must name every column RelayInstall declares. Add a column
    to the model and this passes for free - which is the entire point of deriving it."""
    stmt = snapshot_statement(RelayInstall, _all_columns(RelayInstall))
    selected = [c.name for c in stmt.selected_columns]

    assert selected == _all_columns(RelayInstall)
    # secret_encrypted is the one a reader is most likely to assume got dropped (it is legacy, #382),
    # and losing it would silently orphan a pre-067 relay across a reset.
    assert "secret_encrypted" in selected


def test_skips_a_column_the_live_table_does_not_have_yet():
    """Half-migrated database: the model already declares a column the table predates. Selecting it
    would crash the snapshot, so it is dropped - the same tolerance the has_table guard gives."""
    live = [c for c in _all_columns(RelayInstall) if c != "adopted_by"]

    cols = preserved_columns(RelayInstall, live)

    assert "adopted_by" not in cols
    assert cols == live


def test_ignores_a_live_column_the_model_no_longer_declares():
    """The other direction: a column dropped from the model but still on the live table. It must not
    be carried over, because the rebuilt schema will not have anywhere to put it."""
    cols = preserved_columns(RelayInstall, [*_all_columns(RelayInstall), "column_from_a_past_life"])

    assert cols == _all_columns(RelayInstall)


def test_preserves_model_declaration_order_regardless_of_live_order():
    """Order comes from the model, not from whatever the inspector happens to report, so the SELECT
    and the rows it produces always line up."""
    cols = preserved_columns(RelayInstall, list(reversed(_all_columns(RelayInstall))))

    assert cols == _all_columns(RelayInstall)


def test_no_statement_when_nothing_overlaps():
    """A table that exists but shares no column with the model preserves nothing rather than emitting
    an empty SELECT."""
    assert preserved_columns(RelayInstall, ["totally", "unrelated"]) == []
    assert snapshot_statement(RelayInstall, ["totally", "unrelated"]) is None


def test_projects_are_not_preserved():
    """GP owns jobs, so projects are re-adopted by the forced sync after the rebuild instead of being
    restored. Preserving them would resurrect projects deleted in GP and defeat the reset."""
    assert Project not in PRESERVED_MODELS


def test_buyer_assignments_are_preserved_with_their_cost_codes():
    """The buyer's cost codes are the part that cannot be recovered from GP - the project links can be
    (by job number), the designated cost codes cannot."""
    assert BuyerAssignment in PRESERVED_MODELS
    assert "cost_codes" in preserved_columns(BuyerAssignment, _all_columns(BuyerAssignment))


def test_preserved_models_carry_json_columns():
    """Guards the reason this module builds statements through Core instead of text(): psycopg2 adapts
    a Python list to a Postgres array, so a JSON column round-tripped through a text() bind param fails
    the restore. If this ever stops being true the Core requirement can be revisited - until then it
    is load-bearing."""
    json_columns = [
        (model.__tablename__, c.name)
        for model in PRESERVED_MODELS
        for c in model.__table__.columns
        if c.type.__class__.__name__ in ("JSON", "JSONB")
    ]

    assert json_columns, "expected at least one JSON column among the preserved models"


def test_snapshot_statement_targets_the_models_own_table():
    """Sanity check that the derived SELECT reads the table it claims to - a wrong FROM would preserve
    the wrong rows silently."""
    for model in PRESERVED_MODELS:
        stmt = snapshot_statement(model, _all_columns(model))
        assert sa_inspect(model).local_table.name in str(stmt)
