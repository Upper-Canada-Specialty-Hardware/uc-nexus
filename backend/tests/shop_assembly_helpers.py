"""Batching helpers for the shop-assembly tests (#646).

Creating a request no longer allocates anything, so almost every test that used to say
"create it, accept it" now says "create it, batch it". These wrap the two shapes that come up:
dispatch the whole request, and dispatch a named subset.
"""

from sqlalchemy import select

from app.models.enums import ShopAssemblyOpeningStatus
from app.models.pull_request import PullRequest
from app.repositories import shop_assembly_repository


def batch_lines(session, request_id, *, openings=None, quantities=None):
    """Batch lines for a request's pending openings, at their full owed quantity by default.

    `openings` narrows it to a subset; `quantities` overrides individual lines, keyed by
    (opening_number, hardware_category, product_code), and a 0 leaves that line off the batch.
    """
    request = shop_assembly_repository.get_shop_assembly_request(session, request_id)
    pending = {o.opening_number for o in request.openings if o.status == ShopAssemblyOpeningStatus.PENDING}
    if openings is not None:
        pending &= set(openings)
    overrides = quantities or {}
    lines = []
    for item in request.items:
        if item.opening_number not in pending:
            continue
        key = (item.opening_number, item.hardware_category, item.product_code)
        quantity = overrides.get(key, item.requested_quantity)
        if quantity <= 0:
            continue
        lines.append(
            {
                "opening_number": item.opening_number,
                "hardware_category": item.hardware_category,
                "product_code": item.product_code,
                "allocated_quantity": quantity,
            }
        )
    return lines


def batch_request(session, request_id, *, created_by="manager", openings=None, quantities=None):
    """Dispatch a batch off a pending request and return it."""
    return shop_assembly_repository.create_shop_assembly_batch(
        session,
        request_id,
        batch_lines(session, request_id, openings=openings, quantities=quantities),
        created_by=created_by,
    )


def batch_pull(session, batch):
    """The warehouse pull a batch minted."""
    return session.scalar(select(PullRequest).where(PullRequest.id == batch.pull_request_id))
