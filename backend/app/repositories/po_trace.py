"""Which purchase orders a shipment's hardware came in on (#1732).

The outbound supervisor's drill-down ends at the PO: load, slip, container, line, and then which PO
the item was bought on, so a discrepancy found on site can be followed back to the vendor.

What the records allow is a candidate list, not a single answer, and it is ruled that way (#1721).
A pick names the exact rows it took units off (`pull_pick_lines`), and each row knows the PO it was
received on - but picked hardware then joins the staging floor, which is pooled per product, and a
slip takes its units off that pool rather than off a particular pick. So a slip line's candidates are
every PO the project's shipping picks drew that product from. Usually that is one PO; when it is
several, the line came from one or more of them.
"""

import uuid
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.enums import PullPickLineState, PullRequestSource
from app.models.inventory import InventoryLocation
from app.models.pull_pick_line import PullPickLine
from app.models.pull_request import PullRequest
from app.models.purchase_order import POLineItem, PurchaseOrder
from app.models.shipping import PackingSlip, PackingSlipItem


def slip_candidate_pos(session: Session, packing_slip_id: uuid.UUID) -> dict[uuid.UUID, list[str]]:
    """Each line of a slip, with the POs its product could have come in on. One grouped read for the
    slip's project; a manual line, or one whose stock came from the pool with no PO, gets none."""
    slip = session.get(PackingSlip, packing_slip_id)
    if slip is None:
        return {}
    rows = session.execute(
        select(PullPickLine.hardware_category, PullPickLine.product_code, PurchaseOrder.po_number)
        .distinct()
        .join(PullRequest, PullRequest.id == PullPickLine.pull_request_id)
        .join(InventoryLocation, InventoryLocation.id == PullPickLine.inventory_location_id)
        .join(POLineItem, POLineItem.id == InventoryLocation.po_line_item_id)
        .join(PurchaseOrder, PurchaseOrder.id == POLineItem.po_id)
        .where(
            PullRequest.project_id == slip.project_id,
            PullRequest.source == PullRequestSource.SHIPPING_OUT,
            PullPickLine.state == PullPickLineState.APPLIED,
        )
    ).all()
    by_product: dict[tuple[str, str], set[str]] = defaultdict(set)
    for r in rows:
        by_product[(r.hardware_category, r.product_code)].add(r.po_number)

    lines = session.scalars(select(PackingSlipItem).where(PackingSlipItem.packing_slip_id == packing_slip_id))
    return {
        line.id: ([] if line.is_manual else sorted(by_product.get((line.hardware_category, line.product_code), ())))
        for line in lines
    }
