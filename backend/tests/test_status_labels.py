"""Statuses in refusal messages read as words, not stored constants (#1470)."""

from app.models.enums import POStatus, PullRequestStatus, ReceiveDraftStatus
from app.status_labels import status_label


def test_a_status_reads_as_words():
    assert status_label(POStatus.PARTIALLY_RECEIVED) == "partially received"
    assert status_label(ReceiveDraftStatus.PENDING_APPROVAL) == "pending approval"
    assert status_label(PullRequestStatus.IN_PROGRESS) == "in progress"


def test_gp_stays_an_acronym():
    assert status_label(POStatus.GP_REGISTERED) == "GP registered"


def test_a_plain_string_is_labelled_too():
    assert status_label("VENDOR_CONFIRMED") == "vendor confirmed"
