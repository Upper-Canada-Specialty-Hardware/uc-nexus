"""PO-REQ request numbers are compared as numbers and minted under a lock (#1118).

The max used to be taken over the text column, so once PO-REQ-1000 existed the max was still
"PO-REQ-999" and every later mint collided on the unique index. DB-backed (db_session); each test
works relative to whatever the database already holds, since the rollback fixture keeps other rows.
"""

import uuid

from sqlalchemy import text

from app.models.enums import POStatus
from app.models.purchase_order import PurchaseOrder
from app.repositories.po_repository import generate_next_request_number


def _po(session, request_number: str) -> None:
    session.add(PurchaseOrder(id=uuid.uuid4(), company="TUBC", request_number=request_number, status=POStatus.DRAFT))
    session.flush()


def _seq(number: str) -> int:
    assert number.startswith("PO-REQ-")
    return int(number.removeprefix("PO-REQ-"))


def test_numbering_carries_on_past_999(db_session):
    base = _seq(generate_next_request_number(db_session))
    start = max(base, 998)
    _po(db_session, f"PO-REQ-{start:03d}")
    _po(db_session, f"PO-REQ-{start + 1:03d}")

    nxt = generate_next_request_number(db_session)
    assert _seq(nxt) == start + 2
    _po(db_session, nxt)

    # 1000 and beyond sort before 999 as text; as numbers they keep climbing.
    assert _seq(generate_next_request_number(db_session)) == start + 3


def test_a_suffix_that_is_not_all_digits_is_ignored(db_session):
    base = _seq(generate_next_request_number(db_session))
    _po(db_session, "PO-REQ-9999abc")
    _po(db_session, "PO-REQ-")

    assert _seq(generate_next_request_number(db_session)) == base


def test_minting_takes_the_transaction_scoped_lock(db_session):
    generate_next_request_number(db_session)

    held = db_session.execute(
        text("SELECT count(*) FROM pg_locks WHERE locktype = 'advisory' AND pid = pg_backend_pid() AND granted")
    ).scalar()
    assert held >= 1
