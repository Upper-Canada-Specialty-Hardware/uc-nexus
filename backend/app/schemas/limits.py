"""Bounds on client-chosen list sizes (#1134).

A list resolver that takes `limit` straight from the caller lets one request ask for a company's whole
history, line items and all. 500 is the ceiling the outbox and relay-event lists already used, and it is
above every page size the frontend asks for (the largest is 200)."""

MAX_LIST_LIMIT = 500


def cap_limit(limit: int, maximum: int = MAX_LIST_LIMIT) -> int:
    return max(1, min(limit, maximum))


def cap_offset(offset: int) -> int:
    return max(0, offset)
