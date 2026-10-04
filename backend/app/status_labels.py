"""Statuses as a person reads them, for refusal messages (#1470).

A refusal used to name the stored constant - "Cannot edit PO in PARTIALLY_RECEIVED status", "got
IN_PROGRESS" - which is the database talking. These are almost always reached when somebody else moved
the record a moment before, so the message names the status in words and says what to do next.
"""

from enum import Enum

# Read as an acronym, not as a word.
_ACRONYMS = {"gp": "GP"}

# The step the person can take when what they were looking at has moved on underneath them.
REFRESH_HINT = "It was just changed - refresh to see where it stands."


def status_label(status: Enum | str) -> str:
    """`GP_REGISTERED` -> "GP registered", `PENDING_APPROVAL` -> "pending approval"."""
    raw = status.value if isinstance(status, Enum) else str(status)
    return " ".join(_ACRONYMS.get(word, word) for word in str(raw).lower().split("_"))
