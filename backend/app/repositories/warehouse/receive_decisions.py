""" "This shipment landed - inventory or straight back out?", asked of whoever raised the PO.

The row is minted inside the receive persist (see `create_receive` in receiving.py), which is what
makes it appear on both routes into that persist: the online approval and the outbox worker draining
a receipt that was queued while the relay was down. Answering it records a choice and nothing else -
SHIP_OUT does not build a shipping-out request, because only the hardware schedule knows which
opening and leaf a fungible quantity is owed to (docs/HARDWARE_IDENTITY_LIFECYCLE.md). The frontend
takes the answered decision and deep-links into Start a Task, where that identity gets re-attached.
"""

import uuid
from datetime import datetime

from sqlalchemy import and_, exists, func, or_, select
from sqlalchemy.orm import Session, selectinload

from app.errors import ConflictError, InvalidStateTransitionError, NotFoundError
from app.models.enums import NotificationType, ReceiveDecisionChoice, ReceiveDecisionStatus
from app.models.purchase_order import PurchaseOrder as POModel
from app.models.receive_decision import ReceiveDecision as ReceiveDecisionModel
from app.models.receiving import ReceiveRecord as ReceiveRecordModel
from app.services import notification_service
from app.services.locking import lock_rows


def _same_buyer(a: str | None, b: str | None) -> bool:
    """GP BUYERID comparison, matching `_assert_buyer_identity` in schemas/po.py exactly - char(15)
    out of GP arrives padded and cased however it was typed."""
    if not a or not b:
        return False
    return a.strip().upper() == b.strip().upper()


def create_decision_for_receive(
    session: Session,
    po: POModel,
    receive_record_id: uuid.UUID,
    *,
    total_quantity: int,
) -> ReceiveDecisionModel | None:
    """Raise the keep-or-ship question for a receive that has just been booked.

    Runs inside the persist transaction, so it must not make a network call: `target_user_id` is read
    straight off the PO's column and left NULL when the PO predates it. Resolving that NULL against
    the Clerk roster here would put a Clerk round trip inside the transaction of a GP receipt that has
    already posted, and a Clerk outage would then roll back a receipt GP holds. The read side does
    that resolution instead, for one caller at a time.

    Returns None for a stock PO: "which project's inventory" is not a question you can ask without a
    project.
    """
    if po.project_id is None:
        return None

    existing = session.scalars(
        select(ReceiveDecisionModel).where(ReceiveDecisionModel.receive_record_id == receive_record_id)
    ).first()
    if existing is not None:
        return existing

    decision = ReceiveDecisionModel(
        id=uuid.uuid4(),
        receive_record_id=receive_record_id,
        po_id=po.id,
        project_id=po.project_id,
        target_user_id=po.created_by_user_id,
        status=ReceiveDecisionStatus.PENDING,
    )
    session.add(decision)
    session.flush()

    # Only when we know who to address. An un-addressed notification would go in everyone's bell
    # saying nothing about who has to act; the pending-decisions queue, with its buyer fallback, is
    # what reaches the right person for a PO raised before created_by_user_id existed.
    if po.created_by_user_id:
        notification_service.create_notification(
            session,
            project_id=po.project_id,
            recipient_role=po.created_by_user_id,
            notification_type=NotificationType.RECEIVE_DECISION_REQUIRED,
            message=(
                f"{total_quantity} {'unit' if total_quantity == 1 else 'units'} received against "
                f"PO {po.po_number}. Does this shipment stay in the project's inventory or ship out now?"
            ),
        )
    return decision


def any_untargeted_decision_pending(session: Session) -> bool:
    """Whether any pending decision still needs the GP-buyer fallback to find its owner.

    The fallback exists for POs raised before `created_by_user_id` did, and answering it costs a
    Clerk round trip for the caller's own gpBuyerId. Once those POs are worked through this is false
    forever and the read never touches Clerk again - which matters because the decisions query is on
    the PO list, i.e. one of the most-visited pages in the app.
    """
    return bool(
        session.scalar(
            select(
                exists().where(
                    ReceiveDecisionModel.status == ReceiveDecisionStatus.PENDING,
                    ReceiveDecisionModel.target_user_id.is_(None),
                )
            )
        )
    )


def get_pending_decisions_for_user(
    session: Session,
    user_id: str,
    gp_buyer_id: str | None,
) -> list[tuple[ReceiveDecisionModel, POModel, ReceiveRecordModel]]:
    """The decisions this caller owes an answer to, newest first.

    Two arms. The first is the stamped target - every PO raised since the column existed. The second
    is the fallback for the ones before it: the PO's GP buyer, matched against the caller's OWN
    gpBuyerId. It is a *filter on the caller*, not a search across users, which is what keeps it to a
    single Clerk call - and `any_untargeted_decision_pending` is what lets the resolver skip even
    that when no pre-column PO is outstanding.
    """
    stmt = (
        select(ReceiveDecisionModel, POModel, ReceiveRecordModel)
        .join(POModel, POModel.id == ReceiveDecisionModel.po_id)
        .join(ReceiveRecordModel, ReceiveRecordModel.id == ReceiveDecisionModel.receive_record_id)
        # The card lists every line that came in on the shipment, so the collection is loaded here
        # rather than walked per row by the converter.
        .options(selectinload(ReceiveRecordModel.line_items))
        .where(ReceiveDecisionModel.status == ReceiveDecisionStatus.PENDING)
        .order_by(ReceiveDecisionModel.created_at.desc())
    )
    if gp_buyer_id:
        # UPPER(TRIM(...)) is the SQL half of `_same_buyer`, so the fallback arm matches the way the
        # Python comparison does rather than only on an exact byte match - BUYERID is char(15) and
        # what GP returns is whatever was typed into it.
        stmt = stmt.where(
            or_(
                ReceiveDecisionModel.target_user_id == user_id,
                and_(
                    ReceiveDecisionModel.target_user_id.is_(None),
                    func.upper(func.trim(POModel.buyer_id)) == gp_buyer_id.strip().upper(),
                ),
            )
        )
    else:
        stmt = stmt.where(ReceiveDecisionModel.target_user_id == user_id)
    return [(d, po, rr) for d, po, rr in session.execute(stmt).unique().all()]


def decide_receive_decision(
    session: Session,
    decision_id: uuid.UUID,
    choice: ReceiveDecisionChoice,
    actor_user_id: str,
    actor_name: str,
    load_actor_gp_buyer_id,
    actor_is_admin: bool,
) -> ReceiveDecisionModel:
    """Record the answer.

    Whoever the question was addressed to answers it, resolved the same two ways the read does. An
    admin may answer any of them, which is the escape hatch for the person who raised the PO having
    left - otherwise their decisions would sit pending forever with nobody able to clear them.

    `load_actor_gp_buyer_id` is a callable, not a value, because resolving it is a Clerk round trip
    and it is only an input on the fallback arm - a decision with a stamped target needs nothing from
    Clerk, and every PO raised since that column existed has one. Passing the value eagerly would put
    a Clerk outage in front of decisions that never depended on Clerk.
    """
    lock_rows(session, ReceiveDecisionModel, [decision_id])
    decision = session.get(ReceiveDecisionModel, decision_id)
    if decision is None:
        raise NotFoundError(f"Receive decision {decision_id} not found")
    if decision.status != ReceiveDecisionStatus.PENDING:
        answer = decision.decision.value if decision.decision else "unknown"
        raise InvalidStateTransitionError(f"This shipment decision has already been answered ({answer})")

    po = session.get(POModel, decision.po_id)
    if decision.target_user_id:
        is_target = decision.target_user_id == actor_user_id
    else:
        is_target = _same_buyer(po.buyer_id if po else None, load_actor_gp_buyer_id())
    if not is_target and not actor_is_admin:
        raise ConflictError("This decision is for the person who raised the PO")

    decision.status = ReceiveDecisionStatus.DECIDED
    decision.decision = choice
    decision.decided_by_user_id = actor_user_id
    decision.decided_by_name = actor_name
    decision.decided_at = datetime.utcnow()
    session.flush()
    return decision
