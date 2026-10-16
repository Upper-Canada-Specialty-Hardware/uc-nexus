"""The demo mirror's stored state (#1657): one JSON document per key (see app/models/demo_mirror_state.py)."""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.demo_mirror_state import DemoMirrorState

GP_MASTERS = "gp_masters"
LEGACY_LIST = "legacy_list"
BUILD = "build"
NIGHTLY = "nightly"
# #1697: per user id, the build (by its started_at) they have been told was a reset of the demo.
RESET_SEEN = "reset_seen"


def get(session: Session, key: str) -> dict | None:
    row = session.get(DemoMirrorState, key)
    return dict(row.data) if row else None


def put(session: Session, key: str, data: dict) -> None:
    """Replace the document under `key`. The caller commits."""
    row = session.get(DemoMirrorState, key)
    if row is None:
        session.add(DemoMirrorState(key=key, data=data, updated_at=datetime.utcnow()))
    else:
        # A JSON column is only written back when the attribute is assigned a new object.
        row.data = dict(data)
        row.updated_at = datetime.utcnow()
    session.flush()


def merge(session: Session, key: str, changes: dict) -> dict:
    """Write `changes` over the document under `key`, keeping the rest. The caller commits."""
    data = {**(get(session, key) or {}), **changes}
    put(session, key, data)
    return data


def merge_locked(session: Session, key: str, changes: dict) -> dict:
    """`merge`, holding the row while it reads and writes: for a document many callers write their own
    entry of at once (RESET_SEEN), where two plain merges would each drop the other's entry. The caller
    commits, which releases it."""
    row = session.get(DemoMirrorState, key, with_for_update=True)
    if row is None:
        put(session, key, dict(changes))
        return dict(changes)
    data = {**dict(row.data), **changes}
    row.data = data
    row.updated_at = datetime.utcnow()
    session.flush()
    return data


def keys(session: Session) -> list[str]:
    return list(session.scalars(select(DemoMirrorState.key)))
