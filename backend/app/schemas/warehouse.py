"""Warehouse queries + mutations: receiving, inventory, locations, pull requests, warehouse admin."""

import asyncio
import uuid

import strawberry

from app.auth import (
    ADMIN_ROLE,
    WAREHOUSE_MANAGER_ROLE,
    ForbiddenError,
    caller_roles,
    current_user,
    resolve_display_name,
)
from app.database import SessionLocal
from app.errors import RelayCallError, RelayOpUnsupportedError, RelayTimeoutError, RelayUnavailableError
from app.repositories import user_repository, warehouse_admin_repository
from app.repositories import warehouse as warehouse_repository
from app.services import gp_idempotency, gp_outbox_enqueue, gp_po
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    inventory_location_to_type,
    notification_to_type,
    pick_sheet_to_type,
    po_to_type,
    pull_request_to_type,
    receive_decision_to_type,
    receive_draft_to_type,
    receive_record_to_type,
    stock_item_to_type,
    warehouse_to_type,
)
from .enums import (
    AuditEntityType,
    PickOutcome,
    PullRequestSource,
    PullRequestStatus,
    ReceiveDraftStatus,
)
from .inputs import (
    ApproveReceiveDraftInput,
    CancelPullRequestInput,
    CreateReceiveDraftInput,
    CreateWarehouseInput,
    DecideReceiveDecisionInput,
    OverrideInventoryQuantityInput,
    PickLineInput,
    RejectReceiveDraftInput,
    UpdateReceiveDraftInput,
    UpdateWarehouseInput,
)
from .types import (
    ApproveReceiveDraftResult,
    AuditLogEntry,
    BackOrderedItem,
    CancelPullRequestResult,
    ConfirmPickResult,
    InventoryAvailability,
    InventoryItemDetail,
    InventoryLocation,
    InventoryRow,
    InventoryShortfall,
    LocationContents,
    LocationDistinctValues,
    LocationDuplicateGroup,
    LocationMergeResult,
    LocationUtilizationEntry,
    LocationVariant,
    PickSheet,
    ProjectProgressByProduct,
    PullRequest,
    PurchaseOrder,
    ReceiveDecision,
    ReceiveDraft,
    ReceiveRecord,
    ReceiveRow,
    ReceivingHistoryPO,
    RecentReceiveRecord,
    RestockedLine,
    Warehouse,
    WarehouseDashboard,
)


def _pick_lines_from_input(lines: list[PickLineInput]) -> list[warehouse_repository.PickLine]:
    """GraphQL input -> the repository's `PickLine`. The id parse is the only conversion."""
    return [
        warehouse_repository.PickLine(
            hardware_category=line.hardware_category,
            product_code=line.product_code,
            inventory_location_id=uuid.UUID(str(line.inventory_location_id)),
            quantity=line.quantity,
        )
        for line in lines
    ]


def _partially_picked(session, pr) -> bool | None:
    """Whether stock is off the shelf for an un-picked pull (#367), or None when the question does
    not apply. Every resolver that returns a PullRequest must pass this: the field is part of the
    shared client selection set, so a mutation result that omits it writes null over a cached true."""
    if pr.picked_at is not None:
        return None
    return pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])


def _load_receive_type(receive_id: uuid.UUID) -> ReceiveRecord:
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.receiving import ReceiveRecord as ReceiveRecordModel

    with SessionLocal() as session:
        rec = (
            session.scalars(
                select(ReceiveRecordModel)
                .options(selectinload(ReceiveRecordModel.line_items))
                .where(ReceiveRecordModel.id == receive_id)
            )
            .unique()
            .first()
        )
        return receive_record_to_type(rec)


def _prepare_create_receive(*, po_id, received_by, line_items_data, warehouse_id=None) -> tuple[str, dict]:
    """Read-only: validate the receive is eligible (before the GP receipt is posted) and build the relay
    create_receipt payload. Returns (gp_company, payload).

    The warehouse code rides along because put-away happens after approval now (#501): a line
    normally has no bin yet, and the warehouse is what GP gets told instead of nothing."""
    with SessionLocal() as session:
        po_number, gp_company, receipt_line_items = warehouse_repository.validate_receive_eligibility(
            session, po_id, received_by, line_items_data
        )
        warehouse_code = _warehouse_code(session, warehouse_id)
    payload = gp_po.build_create_receipt_payload(
        po_number=po_number,
        received_by=received_by,
        line_items=receipt_line_items,
        warehouse_code=warehouse_code,
    )
    return gp_company, payload


def _warehouse_code(session, warehouse_id) -> str | None:
    """The receiving warehouse's code, falling back to the primary one the booking will use."""
    from app.models.warehouse import Warehouse as WarehouseModel

    if warehouse_id is None:
        warehouse_id = warehouse_admin_repository.get_primary_warehouse_id(session)
    warehouse = session.get(WarehouseModel, warehouse_id)
    return warehouse.code if warehouse else None


def _receive_outbox_identity(po_id: uuid.UUID) -> tuple[uuid.UUID | None, str]:
    """(project_id, label) for a queued receive (#353 PR E). project_id routes a terminal failure to
    a notification (None when the PO has no project - the worker then relies on the queue UI rather
    than inventing a placeholder project); the label is the human line in that queue. One row."""
    from sqlalchemy import select

    from app.models.purchase_order import PurchaseOrder as POModel

    with SessionLocal() as session:
        row = session.execute(select(POModel.project_id, POModel.po_number).where(POModel.id == po_id)).first()
    project_id = row.project_id if row is not None else None
    number = row.po_number if row is not None else None
    return project_id, f"Receive against PO {number or po_id}"


def _persist_create_receive(
    *, key, po_id, received_by, line_items_data, warehouse_id, relay_result, receive_draft_id=None
) -> ReceiveRecord:
    """Persist the Nexus receive for a GP receipt that has already posted.

    The single persist path for both directions: the resolver calls it after a live relay_call, and
    gp_outbox_worker._persist_create_receive_from_context calls it when a queued receipt finally
    drains. Anything read off `relay_result` therefore has to be read here, or the outbox path
    silently records less than the live one.

    `receipt_number` / `batch_number` are GP's identifiers for the receipt (#447). `.get` rather than
    indexing: a relay old enough to predate them, or a stubbed result in a test, returns a dict
    without the keys, and a missing GP number is worth a null column rather than a failed receive
    against hardware that is physically on the shelf. The fallback is read into its own name rather
    than reassigned - `relay_result` itself is handed to the idempotency ledger, which treats None as
    "this phase recorded nothing, keep what is there" and would take an empty dict as an erasure.

    `receive_draft_id` links the draft this receive was approved from, in the SAME transaction as the
    inventory credit and the ledger stamp - so a draft can never read as approved without the receive
    that proves it, or the other way round. Defaulted because the outbox can still hold rows enqueued
    before drafts existed.
    """
    gp_receipt = relay_result or {}
    with SessionLocal() as session:
        receive_record = warehouse_repository.create_receive(
            session,
            po_id,
            received_by,
            line_items_data,
            warehouse_id=warehouse_id,
            receipt_number=gp_receipt.get("receipt_number"),
            batch_number=gp_receipt.get("batch_number"),
            # #499: so the booking stamps its receive onto the decision the count already raised,
            # rather than raising a second one nobody asked for.
            receive_draft_id=receive_draft_id,
        )
        # Capture the id before commit: expire_on_commit would make receive_record.id raise
        # DetachedInstanceError once the session block closes.
        receive_id = receive_record.id
        if receive_draft_id is not None:
            warehouse_repository.mark_approved(session, receive_draft_id, receive_record_id=receive_id)
        gp_idempotency.stamp_result_id(session, key, "create_receive", relay_result, str(receive_id))
        session.commit()
    return _load_receive_type(receive_id)


def _receive_line_items_data(line_items) -> list[dict]:
    """GraphQL receive lines -> the dict shape the repositories and the outbox context speak."""
    return [
        {
            "po_line_item_id": uuid.UUID(str(li.po_line_item_id)),
            "quantity_received": li.quantity_received,
            "locations": [
                {
                    "aisle": loc.aisle,
                    "row": loc.row,
                    "bay": loc.bay,
                    "quantity": loc.quantity,
                    "deficient_quantity": loc.deficient_quantity,
                }
                for loc in li.locations
            ],
        }
        for li in line_items
    ]


def _is_warehouse_manager(info) -> bool:
    """Whether the caller may act on somebody else's draft. Reads the per-request role memo, so this
    adds no Clerk call on a field whose policy already resolved roles."""
    roles = set(caller_roles(info.context))
    return bool(roles & {ADMIN_ROLE, WAREHOUSE_MANAGER_ROLE})


def _load_draft_type(draft_id: uuid.UUID) -> ReceiveDraft:
    with SessionLocal() as session:
        draft, po, decision = warehouse_repository.get_receive_draft(session, draft_id)
        return receive_draft_to_type(draft, po, decision)


def _may_book_draft(decision, user_id: str, *, is_manager: bool) -> bool:
    """Whether this caller may book the draft the decision belongs to (#499).

    A Warehouse Manager or an admin, as before. Plus exactly one more: the PO creator who answered
    SHIP_OUT on this very draft. Their answer means the hardware is not staying, so making them wait
    on a queue whose purpose is to decide where in the warehouse it goes is a step that no longer
    means anything. KEEP does not qualify - that answer says it IS staying, which is the case the
    manager's approval is for.

    Pure so it can be pinned directly. The decision is read from the database by the caller below,
    never from anything the client sends.
    """
    from app.models.enums import ReceiveDecisionChoice

    if is_manager:
        return True
    return (
        decision is not None
        and decision.decision == ReceiveDecisionChoice.SHIP_OUT
        and decision.decided_by_user_id == user_id
    )


def _authorize_draft_approval(info, user_id: str, draft_id: uuid.UUID) -> None:
    """Refuse a draft approval this caller is not entitled to (#499)."""
    from sqlalchemy import select

    from app.models.receive_decision import ReceiveDecision as ReceiveDecisionModel

    is_manager = bool(set(caller_roles(info.context)) & {ADMIN_ROLE, WAREHOUSE_MANAGER_ROLE})
    if is_manager:
        return
    with SessionLocal() as session:
        decision = session.scalars(
            select(ReceiveDecisionModel).where(ReceiveDecisionModel.receive_draft_id == draft_id)
        ).first()
    if not _may_book_draft(decision, user_id, is_manager=False):
        raise ForbiddenError("Only a Warehouse Manager can approve this receive.")


def _load_decision(session, decision_id: uuid.UUID):
    """(decision, po, receive_record) for one decision, with the receive's lines eager-loaded - the
    decision card lists everything that came in on that shipment."""
    from sqlalchemy import select
    from sqlalchemy.orm import selectinload

    from app.models.purchase_order import PurchaseOrder as POModel
    from app.models.receive_decision import ReceiveDecision as ReceiveDecisionModel
    from app.models.receiving import ReceiveRecord as ReceiveRecordModel

    decision = session.get(ReceiveDecisionModel, decision_id)
    po = session.get(POModel, decision.po_id)
    receive_record = (
        session.scalars(
            select(ReceiveRecordModel)
            .options(selectinload(ReceiveRecordModel.line_items))
            .where(ReceiveRecordModel.id == decision.receive_record_id)
        )
        .unique()
        .first()
    )
    return decision, po, receive_record


def _claim_draft_for_approval(draft_id, reviewer_user_id, reviewer_name, key):
    """Take the approval claim and COMMIT it, before anything talks to GP.

    Committing here rather than at the end is the whole point: the claim has to be visible to another
    request while this one is waiting on the relay, which is exactly the window a second approver
    would otherwise post a duplicate GP receipt in.
    """
    with SessionLocal() as session:
        ctx = warehouse_repository.claim_for_approval(session, draft_id, reviewer_user_id, reviewer_name, key)
        session.commit()
    return ctx


def _json_line_items(line_items_data: list[dict]) -> list[dict]:
    """The claimed lines with their UUIDs stringified, for a queued approval's outbox persist_context.

    Derived from the context the claim already built rather than re-read: the outbox row is JSON, and
    the only difference from what is in hand is the id type."""
    return [
        {
            "po_line_item_id": str(li["po_line_item_id"]),
            "quantity_received": li["quantity_received"],
            "locations": li["locations"],
        }
        for li in line_items_data
    ]


def _release_draft_claim(draft_id, key) -> None:
    with SessionLocal() as session:
        warehouse_repository.release_approval_claim(session, draft_id, key)
        session.commit()


def _mark_draft_queued(draft_id, outbox_entry_id) -> None:
    """The approval reached the outbox rather than GP. The draft is finished from the reviewer's side
    - what it must not be is approvable again, which would enqueue a second receipt."""
    with SessionLocal() as session:
        warehouse_repository.mark_approved(session, draft_id, outbox_entry_id=uuid.UUID(str(outbox_entry_id)))
        session.commit()


@strawberry.type
class WarehouseQueries:
    @strawberry.field
    def po_receiving_details(self, info: strawberry.Info, po_id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po, receive_records = warehouse_repository.get_po_receiving_details(session, uuid.UUID(str(po_id)))
            return po_to_type(po, receive_records)

    @strawberry.field
    def receive_drafts(
        self,
        info: strawberry.Info,
        status: ReceiveDraftStatus | None = None,
        po_id: strawberry.ID | None = None,
        mine: bool = False,
    ) -> list[ReceiveDraft]:
        """Counted receives waiting on (or returned from) approval, newest first.

        `mine` scopes to the caller's own drafts - what a warehouse user needs to see is the state of
        their own counts, and what a manager needs is everybody's. Signed-in rather than
        manager-gated for the same reason: a rejected draft is only actionable by its author.
        """
        from app.models.enums import ReceiveDraftStatus as ReceiveDraftStatusDB

        user = current_user(info)
        with SessionLocal() as session:
            rows = warehouse_repository.get_receive_drafts(
                session,
                status=ReceiveDraftStatusDB(status.value) if status is not None else None,
                po_id=uuid.UUID(str(po_id)) if po_id else None,
                created_by_user_id=user["user_id"] if mine else None,
            )
            return [receive_draft_to_type(draft, po, decision) for draft, po, decision in rows]

    @strawberry.field
    def receive_draft(self, info: strawberry.Info, id: strawberry.ID) -> ReceiveDraft:
        with SessionLocal() as session:
            draft, po, decision = warehouse_repository.get_receive_draft(session, uuid.UUID(str(id)))
            return receive_draft_to_type(draft, po, decision)

    @strawberry.field
    def my_receive_decisions(self, info: strawberry.Info) -> list[ReceiveDecision]:
        """Shipments waiting on this caller to say where they go.

        The caller's own GP buyer id answers the fallback arm - the POs raised before
        `created_by_user_id` existed - and it costs a Clerk round trip, so it is fetched only when
        such a PO is actually outstanding. This query is on the PO list, which is one of the
        most-visited pages in the app; paying Clerk on every mount for a fallback that matches
        nothing would be the wrong default. It is also specifically NOT resolved inside the receive
        persist, where a Clerk outage would roll back a GP receipt that had already posted.
        """
        user = current_user(info)
        with SessionLocal() as session:
            gp_buyer_id = (
                user_repository.get_user_gp_buyer_id(user["user_id"])
                if warehouse_repository.any_untargeted_decision_pending(session)
                else None
            )
            rows = warehouse_repository.get_pending_decisions_for_user(session, user["user_id"], gp_buyer_id)
            return [receive_decision_to_type(d, po, rr, draft) for d, po, rr, draft in rows]

    @strawberry.field
    def project_inventory_availability(
        self, info: strawberry.Info, project_id: strawberry.ID
    ) -> list[InventoryAvailability]:
        """What each product in a project can still be claimed for (#342):
        `available = on_hand - deficient - reserved`.

        This is the number the Start-a-Request creation gate applies, exposed so the wizard can block an
        over-selection with per-combo detail *before* submission rather than bouncing the whole
        finalize. Deliberately distinct from `inventoryHierarchy`'s availability, which is on-hand
        minus deficient: that answers "what is physically unspoken-for in the building", this
        answers "what may I claim". Two grouped scalar aggregates, no per-row work."""
        with SessionLocal() as session:
            rows = warehouse_repository.get_project_availability(session, uuid.UUID(str(project_id)))
            return [
                InventoryAvailability(
                    hardware_category=row["hardware_category"],
                    product_code=row["product_code"],
                    on_hand_quantity=row["on_hand_quantity"],
                    deficient_quantity=row["deficient_quantity"],
                    reserved_quantity=row["reserved_quantity"],
                    available_quantity=row["available_quantity"],
                )
                for row in rows
            ]

    @strawberry.field
    def receives(
        self,
        info: strawberry.Info,
        limit: int = 50,
        offset: int = 0,
        project_id: strawberry.ID | None = None,
        po_search: str | None = None,
    ) -> list[ReceiveRow]:
        """Every receive entity, drafts and booked records interleaved, newest first (#505).

        The existing views each cover a slice and a rejected draft appeared in none of them, so a
        disputed count vanished from the product entirely."""
        with SessionLocal() as session:
            return [
                ReceiveRow(
                    kind=r["kind"],
                    id=strawberry.ID(str(r["id"])),
                    occurred_at=r["occurred_at"],
                    status=r["status"],
                    po_id=strawberry.ID(str(r["po_id"])),
                    po_number=r["po_number"],
                    project_id=strawberry.ID(str(r["project_id"])) if r["project_id"] else None,
                    project_name=r["project_name"],
                    warehouse_id=strawberry.ID(str(r["warehouse_id"])) if r["warehouse_id"] else None,
                    line_count=r["line_count"],
                    total_quantity=r["total_quantity"],
                    counted_by=r["counted_by"],
                    reviewed_by=r["reviewed_by"],
                    rejection_reason=r["rejection_reason"],
                    receipt_number=r["receipt_number"],
                    batch_number=r["batch_number"],
                )
                for r in warehouse_repository.get_all_receives(
                    session,
                    limit=limit,
                    offset=offset,
                    project_id=uuid.UUID(str(project_id)) if project_id else None,
                    po_search=po_search,
                )
            ]

    @strawberry.field
    def inventory_rows(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        warehouse_id: strawberry.ID | None = None,
    ) -> list[InventoryRow]:
        """Flat inventory, one row per stocked location (#506). Replaces the accordion the Hardware
        Items tab used to render; one query, no per-row lazy loads."""
        with SessionLocal() as session:
            return [
                InventoryRow(
                    inventory_location=inventory_location_to_type(r["inventory_location"]),
                    unit_cost=r["unit_cost"],
                    line_value=r["line_value"],
                    po_number=r["po_number"],
                    vendor_name=r["vendor_name"],
                    warehouse_code=r["warehouse_code"],
                    warehouse_name=r["warehouse_name"],
                    project_number=r["project_number"],
                    project_name=r["project_name"],
                )
                for r in warehouse_repository.get_inventory_rows(
                    session,
                    uuid.UUID(str(project_id)) if project_id else None,
                    uuid.UUID(str(warehouse_id)) if warehouse_id else None,
                )
            ]

    @strawberry.field
    def unlocated_inventory(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        warehouse_id: strawberry.ID | None = None,
    ) -> list[InventoryItemDetail]:
        with SessionLocal() as session:
            items = warehouse_repository.get_unlocated_inventory(
                session,
                uuid.UUID(str(project_id)) if project_id else None,
                uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            return [
                InventoryItemDetail(
                    inventory_location=inventory_location_to_type(item["inventory_location"]),
                    po_number=item["po_number"],
                    classification=item["classification"],
                    unit_cost=item["unit_cost"],
                )
                for item in items
            ]

    @strawberry.field
    def recent_receive_records(self, info: strawberry.Info, limit: int = 10) -> list[RecentReceiveRecord]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_recent_receive_records(session, limit)
            return [
                RecentReceiveRecord(
                    receive_record=receive_record_to_type(rr),
                    po_number=po.po_number,
                    total_items_received=sum(rli.quantity_received for rli in rr.line_items),
                )
                for rr, po in rows
            ]

    @strawberry.field
    def receiving_history_pos(
        self, info: strawberry.Info, project_id: strawberry.ID | None = None
    ) -> list[ReceivingHistoryPO]:
        """Every GP-registered PO with what has landed against it (#447).

        The complement to `openPOs` and `backOrderedItems`, which answer "what is still owed" and so
        drop a PO the moment it is complete. Reconciling a delivery against GP needs the completed
        ones, which is why CLOSED is in scope here and nowhere else on this page. One row per PO,
        built from grouped aggregates in the repository - the per-PO receives come from
        `poReceivingDetails` when a row is expanded, not from here."""
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id)) if project_id else None
            return [
                ReceivingHistoryPO(
                    id=strawberry.ID(str(row["id"])),
                    po_number=row["po_number"],
                    request_number=row["request_number"],
                    status=row["status"],
                    vendor_name=row["vendor_name"],
                    project_id=strawberry.ID(str(row["project_id"])) if row["project_id"] else None,
                    ordered_total=row["ordered_total"],
                    received_total=row["received_total"],
                    receive_count=row["receive_count"],
                    last_received_at=row["last_received_at"],
                )
                for row in warehouse_repository.get_receiving_history_pos(session, pid)
            ]

    @strawberry.field
    def pull_requests(
        self,
        info: strawberry.Info,
        project_id: strawberry.ID | None = None,
        source: PullRequestSource | None = None,
        status: PullRequestStatus | None = None,
    ) -> list[PullRequest]:
        with SessionLocal() as session:
            prs = warehouse_repository.get_pull_requests(
                session, uuid.UUID(str(project_id)) if project_id else None, source, status
            )
            # One grouped read for the whole page, never one query per row (#367 / CLAUDE.md perf
            # rules): the queue draws a phase cell on every row. Narrowed to un-picked pulls, which
            # are the only ones it means anything for.
            partial = warehouse_repository.get_partially_picked_pull_ids(
                session, [pr.id for pr in prs if pr.picked_at is None]
            )
            return [
                pull_request_to_type(
                    pr,
                    partially_picked=(pr.id in partial) if pr.picked_at is None else None,
                )
                for pr in prs
            ]

    @strawberry.field
    def pull_request_details(self, info: strawberry.Info, id: strawberry.ID) -> PullRequest:
        with SessionLocal() as session:
            pr = warehouse_repository.get_pull_request_details(session, uuid.UUID(str(id)))
            partial = (
                pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])
                if pr.picked_at is None
                else None
            )
            return pull_request_to_type(pr, partially_picked=partial)

    @strawberry.field
    def pull_pick_sheet(self, info: strawberry.Info, pull_request_id: strawberry.ID) -> PickSheet:
        """Everything the pick screen and the printed sheet render from (#367).

        A query of its own rather than a field on `PullRequest`, for the same reason
        `pullRequestOpenings` is: a resolver field would run once per row of the pull-request queue,
        and the queue never needs it - only the pick page does.

        Open to any signed-in user. It exposes real per-location inventory for one project, which is
        the same shape of information the warehouse inventory views already carry."""
        with SessionLocal() as session:
            sheet = warehouse_repository.get_pick_sheet(session, uuid.UUID(str(pull_request_id)))
            pr = sheet.pull_request
            partial = (
                pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])
                if pr.picked_at is None
                else None
            )
            return pick_sheet_to_type(sheet, partially_picked=partial)

    @strawberry.field
    def back_ordered_items(
        self, info: strawberry.Info, project_id: strawberry.ID | None = None
    ) -> list[BackOrderedItem]:
        with SessionLocal() as session:
            items = warehouse_repository.get_back_ordered_items(
                session, uuid.UUID(str(project_id)) if project_id else None
            )
            return [
                BackOrderedItem(
                    po_line_item_id=strawberry.ID(str(item["po_line_item"].id)),
                    hardware_category=item["po_line_item"].hardware_category,
                    product_code=item["po_line_item"].product_code,
                    ordered_quantity=item["po_line_item"].ordered_quantity,
                    received_quantity=item["po_line_item"].received_quantity,
                    outstanding_quantity=item["outstanding_quantity"],
                    po_number=item["po_number"],
                    vendor_name=item["vendor_name"],
                    expected_delivery_date=item["expected_delivery_date"],
                    project_name=item["project_name"],
                )
                for item in items
            ]

    @strawberry.field
    def warehouse_dashboard(self, info: strawberry.Info) -> WarehouseDashboard:
        with SessionLocal() as session:
            d = warehouse_repository.get_warehouse_dashboard(session)
            return WarehouseDashboard(
                total_item_count=d["total_item_count"],
                total_value=d["total_value"],
                unlocated_count=d["unlocated_count"],
                stock_item_count=d["stock_item_count"],
                stock_unlocated_count=d["stock_unlocated_count"],
                pending_pull_shop=d["pending_pull_shop"],
                pending_pull_shipping=d["pending_pull_shipping"],
                received_last_7_days=d["received_last_7_days"],
                back_ordered_count=d["back_ordered_count"],
                deficient_count=d["deficient_count"],
                pending_receive_draft_count=d["pending_receive_draft_count"],
            )

    @strawberry.field
    def project_progress_by_product(
        self, info: strawberry.Info, project_id: strawberry.ID
    ) -> list[ProjectProgressByProduct]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_project_progress_by_product(session, uuid.UUID(str(project_id)))
            return [
                ProjectProgressByProduct(
                    hardware_category=row["hardware_category"],
                    product_code=row["product_code"],
                    required_quantity=row["required_quantity"],
                    po_drafted=row["po_drafted"],
                    ordered_quantity=row["ordered_quantity"],
                    received_quantity=row["received_quantity"],
                    back_ordered=row["back_ordered"],
                    shipped_out=row["shipped_out"],
                )
                for row in rows
            ]

    @strawberry.field
    def location_contents(
        self,
        info: strawberry.Info,
        aisle: str,
        row: str | None = None,
        bay: str | None = None,
        warehouse_id: strawberry.ID | None = None,
    ) -> LocationContents:
        with SessionLocal() as session:
            data = warehouse_repository.get_location_contents(
                session, aisle, row, bay, uuid.UUID(str(warehouse_id)) if warehouse_id else None
            )
            return LocationContents(
                inventory_items=[
                    InventoryItemDetail(
                        inventory_location=inventory_location_to_type(item["inventory_location"]),
                        po_number=item["po_number"],
                        classification=None,
                        unit_cost=item["unit_cost"],
                    )
                    for item in data["inventory_items"]
                ],
                stock_items=[stock_item_to_type(si) for si in data["stock_items"]],
            )

    @strawberry.field
    def location_audit_history(
        self,
        info: strawberry.Info,
        aisle: str,
        row: str | None = None,
        bay: str | None = None,
        limit: int = 10,
        warehouse_id: strawberry.ID | None = None,
    ) -> list[AuditLogEntry]:
        with SessionLocal() as session:
            entries = warehouse_repository.get_location_audit_history(
                session,
                aisle,
                row,
                bay,
                limit=limit,
                warehouse_id=uuid.UUID(str(warehouse_id)) if warehouse_id else None,
            )
            return [
                AuditLogEntry(
                    id=strawberry.ID(str(e.id)),
                    project_id=strawberry.ID(str(e.project_id)) if e.project_id else None,
                    entity_type=e.entity_type,
                    entity_id=strawberry.ID(str(e.entity_id)),
                    action=e.action,
                    detail=e.detail,
                    performed_by=e.performed_by,
                    created_at=e.created_at,
                )
                for e in entries
            ]

    @strawberry.field
    def location_distinct_values(self, info: strawberry.Info) -> LocationDistinctValues:
        with SessionLocal() as session:
            values = warehouse_repository.get_distinct_location_values(session)
            return LocationDistinctValues(
                aisles=values["aisles"],
                rows=values["rows"],
                bays=values["bays"],
            )

    @strawberry.field
    def location_duplicates(self, info: strawberry.Info) -> list[LocationDuplicateGroup]:
        """Admin-gated (#415): the admin Location Cleanup page is the only reader, and it is the
        list `mergeLocations` acts on."""
        with SessionLocal() as session:
            groups = warehouse_repository.get_location_duplicates(session)
            return [
                LocationDuplicateGroup(
                    warehouse_id=strawberry.ID(str(g["warehouse_id"])) if g["warehouse_id"] else None,
                    warehouse_label=g["warehouse_label"],
                    canonical_aisle=g["canonical_aisle"],
                    canonical_row=g["canonical_row"],
                    canonical_bay=g["canonical_bay"],
                    variants=[LocationVariant(aisle=v["aisle"], row=v["row"], bay=v["bay"]) for v in g["variants"]],
                )
                for g in groups
            ]

    @strawberry.field
    def location_utilization(
        self, info: strawberry.Info, warehouse_id: strawberry.ID | None = None
    ) -> list[LocationUtilizationEntry]:
        with SessionLocal() as session:
            rows = warehouse_repository.get_location_utilization(
                session, uuid.UUID(str(warehouse_id)) if warehouse_id else None
            )
            return [
                LocationUtilizationEntry(
                    warehouse_id=strawberry.ID(str(r["warehouse_id"])) if r.get("warehouse_id") else None,
                    aisle=r["aisle"],
                    row=r["row"],
                    bay=r["bay"],
                    item_count=r["item_count"],
                    total_quantity=r["total_quantity"],
                )
                for r in rows
            ]

    @strawberry.field
    def audit_log(
        self,
        info: strawberry.Info,
        entity_id: strawberry.ID | None = None,
        entity_type: AuditEntityType | None = None,
        project_id: strawberry.ID | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[AuditLogEntry]:
        with SessionLocal() as session:
            entries = warehouse_repository.get_audit_log(
                session,
                entity_id=uuid.UUID(str(entity_id)) if entity_id else None,
                entity_type=entity_type.value if entity_type else None,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
                limit=limit,
                offset=offset,
            )
            return [
                AuditLogEntry(
                    id=strawberry.ID(str(e.id)),
                    project_id=strawberry.ID(str(e.project_id)) if e.project_id else None,
                    entity_type=e.entity_type,
                    entity_id=strawberry.ID(str(e.entity_id)),
                    action=e.action,
                    detail=e.detail,
                    performed_by=e.performed_by,
                    created_at=e.created_at,
                )
                for e in entries
            ]

    @strawberry.field
    def warehouses(self, info: strawberry.Info, include_inactive: bool = True) -> list[Warehouse]:
        """Signed-in, not admin (#415): the receive, transfer and return dialogs all read this
        list to populate a warehouse picker, so it is not admin-only even though its writes are."""
        with SessionLocal() as session:
            return [
                warehouse_to_type(w)
                for w in warehouse_admin_repository.list_warehouses(session, include_inactive=include_inactive)
            ]

    @strawberry.field
    def warehouse(self, info: strawberry.Info, id: strawberry.ID) -> Warehouse | None:
        with SessionLocal() as session:
            w = warehouse_admin_repository.find_warehouse(session, uuid.UUID(str(id)))
            return warehouse_to_type(w) if w is not None else None


@strawberry.type
class WarehouseMutations:
    # Receiving: a counted delivery becomes a draft, and approving it is what reaches GP.
    @strawberry.mutation
    def create_receive_draft(self, info: strawberry.Info, input: CreateReceiveDraftInput) -> ReceiveDraft:
        """Record what somebody counted off a truck, for a Warehouse Manager to approve.

        Nothing here touches GP or inventory - that is the point of the split. The eligibility rules
        still run (over-receive, PO status, location sums, the #425 GP-setup quarantine), because a
        draft nobody could ever approve is worth refusing in front of the person holding the packing
        slip rather than hours later in somebody else's queue.

        The author is the Clerk-authenticated caller (#199/#427): their display name is captured here
        and becomes `ReceiveRecord.received_by` at approval, so the receive records who did the
        receiving rather than who signed it off.
        """
        user = current_user(info)
        author_name = resolve_display_name(user["user_id"])
        with SessionLocal() as session:
            draft = warehouse_repository.create_receive_draft(
                session,
                uuid.UUID(str(input.po_id)),
                _receive_line_items_data(input.line_items),
                user["user_id"],
                author_name,
                warehouse_id=uuid.UUID(str(input.warehouse_id)) if input.warehouse_id else None,
                idempotency_key=(input.idempotency_key or "").strip() or None,
                packing_slip_document_id=(
                    uuid.UUID(str(input.packing_slip_document_id)) if input.packing_slip_document_id else None
                ),
            )
            draft_id = draft.id
            session.commit()
        return _load_draft_type(draft_id)

    @strawberry.mutation
    def update_receive_draft(self, info: strawberry.Info, input: UpdateReceiveDraftInput) -> ReceiveDraft:
        """Correct a draft: a manager fixing a count before approving it, or its author answering a
        rejection. Author-or-manager is decided in the body, because it depends on whose draft it is."""
        user = current_user(info)
        draft_id = uuid.UUID(str(input.draft_id))
        with SessionLocal() as session:
            warehouse_repository.update_receive_draft(
                session,
                draft_id,
                _receive_line_items_data(input.line_items),
                user["user_id"],
                _is_warehouse_manager(info),
                warehouse_id=uuid.UUID(str(input.warehouse_id)) if input.warehouse_id else None,
            )
            session.commit()
        return _load_draft_type(draft_id)

    @strawberry.mutation
    def resubmit_receive_draft(self, info: strawberry.Info, id: strawberry.ID) -> ReceiveDraft:
        """Put a rejected draft back in the approval queue. Its author only."""
        user = current_user(info)
        draft_id = uuid.UUID(str(id))
        with SessionLocal() as session:
            warehouse_repository.resubmit_receive_draft(session, draft_id, user["user_id"])
            session.commit()
        return _load_draft_type(draft_id)

    @strawberry.mutation
    def reject_receive_draft(self, info: strawberry.Info, input: RejectReceiveDraftInput) -> ReceiveDraft:
        """Send a draft back to its author with a reason. The reviewer is the Clerk-authenticated
        caller (#427)."""
        user = current_user(info)
        reviewer_name = resolve_display_name(user["user_id"])
        draft_id = uuid.UUID(str(input.draft_id))
        with SessionLocal() as session:
            warehouse_repository.reject_receive_draft(session, draft_id, input.reason, user["user_id"], reviewer_name)
            session.commit()
        return _load_draft_type(draft_id)

    @strawberry.mutation
    def delete_receive_draft(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        """Throw away a count that should not have been entered. Refused once approval has started."""
        user = current_user(info)
        with SessionLocal() as session:
            warehouse_repository.delete_receive_draft(
                session, uuid.UUID(str(id)), user["user_id"], _is_warehouse_manager(info)
            )
            session.commit()
        return True

    @strawberry.mutation
    async def approve_receive_draft(
        self, info: strawberry.Info, input: ApproveReceiveDraftInput
    ) -> ApproveReceiveDraftResult:
        """Approve a drafted receive: post the GP receipt, then book it into UC Nexus.

        This is `createReceive` (#199/#202) with a claim in front of it - the pipeline is otherwise
        untouched, and deliberately so. GP-first ordering, the idempotency ledger, the outbox fallback
        for an unreachable relay and the re-validation before anything is posted all behave exactly as
        they did when this ran at submission time.

        What the split adds:

        - `received_by` is the DRAFT AUTHOR's name, read off the draft. The approver's identity goes
          on the draft's review fields. Neither comes from the client (#427).
        - The claim (`_claim_draft_for_approval`) is committed before the relay call, because a
          database lock cannot span a network round trip. It is what makes a second approver bounce
          off instead of posting a duplicate receipt.
        - Whether a failure releases that claim is decided by ONE question: can GP be holding the
          receipt? Everything that answers "no" - validation, an eConnect refusal, a relay too old
          for the op - releases, because a draft parked where nobody can act on it is worse than the
          error itself. Everything ambiguous - a dispatched disconnect, a timeout - keeps the claim,
          because releasing it invites a second receipt for hardware GP may already have booked.
          A parked draft is recoverable: `approvalIdempotencyKey` is on the type, so the reviewer's
          retry resumes through the ledger rather than starting a new approval.

        Since #499 a Warehouse Manager is not the only caller. A PO creator who answered SHIP_OUT is
        saying this delivery never enters their queue - it goes straight back out - so they book it
        themselves and carry straight on into the shipping request. That is a narrow bypass and it is
        checked against the database, not the client: the caller must own an undecided-elsewhere
        SHIP_OUT decision on THIS draft. Nothing else about the pipeline changes; the receipt is
        posted GP-first through the same ledger either way.
        """
        user = current_user(info)
        key = gp_idempotency.validate_key(input.idempotency_key)
        draft_id = uuid.UUID(str(input.draft_id))
        await asyncio.to_thread(_authorize_draft_approval, info, user["user_id"], draft_id)

        state = await asyncio.to_thread(gp_idempotency.load, key)
        if state is not None and state.result_id is not None:
            # Fully finished under this key already. The draft link was written in the same
            # transaction as the receive, so there is nothing to repair - just answer with it.
            record = await asyncio.to_thread(_load_receive_type, uuid.UUID(state.result_id))
            draft = await asyncio.to_thread(_load_draft_type, draft_id)
            return ApproveReceiveDraftResult(queued=False, outbox_entry_id=None, receive_record=record, draft=draft)

        reviewer_name = await asyncio.to_thread(resolve_display_name, user["user_id"])
        ctx = await asyncio.to_thread(_claim_draft_for_approval, draft_id, user["user_id"], reviewer_name, key)
        # GP has ALREADY run under this key and only the persist is outstanding. Re-validating here
        # would be re-asking a question GP has answered: the world can have moved since (another
        # receive against the line), and a refusal would release the claim for a receipt that is
        # sitting in GP - after which a fresh key would post a second one.
        resuming = state is not None and state.relay_result is not None

        if resuming:
            relay_result = state.relay_result
        else:
            try:
                gp_company, payload = await asyncio.to_thread(
                    _prepare_create_receive,
                    po_id=ctx.po_id,
                    received_by=ctx.author_name,
                    line_items_data=ctx.line_items_data,
                    warehouse_id=ctx.warehouse_id,
                )
            except Exception:
                # Nothing reached GP, so the draft belongs back in the queue with the reason surfaced
                # to the reviewer.
                await asyncio.to_thread(_release_draft_claim, draft_id, key)
                raise

            try:
                relay_result = await relay_gateway.relay_call(gp_company, "create_receipt", payload)
            except (RelayCallError, RelayOpUnsupportedError):
                # The relay answered: eConnect refused it, or this build cannot run the op. Either
                # way GP did not commit, so the draft goes back in the queue for whoever fixes the
                # cause - the #425 quarantine being the usual one.
                await asyncio.to_thread(_release_draft_claim, draft_id, key)
                raise
            except RelayTimeoutError:
                # Ambiguous: the job was on the wire and GP may have posted it. Keep the claim so
                # nobody else approves it, and let the same key resume.
                raise
            except RelayUnavailableError as e:
                # #353 PR E: the receipt never left the backend, so GP cannot have posted it - queue
                # it rather than failing a warehouse user who has already counted the hardware. A
                # DISPATCHED failure is re-raised WITH the claim held: GP may hold the receipt, and a
                # blind retry would double-count inventory.
                if not gp_outbox_enqueue.may_enqueue(e):
                    raise
                json_line_items = _json_line_items(ctx.line_items_data)
                project_id, label = await asyncio.to_thread(_receive_outbox_identity, ctx.po_id)
                entry_id = await asyncio.to_thread(
                    gp_outbox_enqueue.enqueue,
                    idempotency_key=key,
                    op="create_receive",
                    relay_op="create_receipt",
                    company=gp_company,
                    payload=payload,
                    persist_context={
                        "po_id": str(ctx.po_id),
                        "received_by": ctx.author_name,
                        "warehouse_id": str(ctx.warehouse_id) if ctx.warehouse_id else None,
                        "line_items_data": json_line_items,
                        # The worker links the draft when it drains, on the same helper this resolver
                        # calls - so the two routes into the persist cannot record different things.
                        "receive_draft_id": str(draft_id),
                    },
                    # Same entity_key as register_po_in_gp so a receipt can never be drained ahead of
                    # the registration of the PO it is against.
                    entity_key=f"po:{ctx.po_id}",
                    label=label,
                    project_id=project_id,
                    requested_by=user["user_id"],
                )
                await asyncio.to_thread(_mark_draft_queued, draft_id, entry_id)
                draft = await asyncio.to_thread(_load_draft_type, draft_id)
                # Nothing is in inventory yet - the persist is deferred with the GP write.
                return ApproveReceiveDraftResult(
                    queued=True,
                    outbox_entry_id=strawberry.ID(entry_id),
                    receive_record=None,
                    draft=draft,
                )
            await asyncio.to_thread(gp_idempotency.record_relay_result, key, "create_receive", relay_result)

        record = await asyncio.to_thread(
            _persist_create_receive,
            key=key,
            po_id=ctx.po_id,
            received_by=ctx.author_name,
            line_items_data=ctx.line_items_data,
            warehouse_id=ctx.warehouse_id,
            relay_result=relay_result,
            receive_draft_id=draft_id,
        )
        draft = await asyncio.to_thread(_load_draft_type, draft_id)
        return ApproveReceiveDraftResult(queued=False, outbox_entry_id=None, receive_record=record, draft=draft)

    @strawberry.mutation
    def decide_receive_decision(self, info: strawberry.Info, input: DecideReceiveDecisionInput) -> ReceiveDecision:
        """Answer the keep-or-ship question a landed shipment raised.

        Recording the answer is all this does. SHIP_OUT does not build a shipping-out request: only
        the hardware schedule knows which opening and leaf a fungible quantity is owed to, so the
        frontend takes the recorded choice and deep-links into Start a Request, where that identity is
        re-attached (docs/HARDWARE_IDENTITY_LIFECYCLE.md).
        """
        from app.models.enums import ReceiveDecisionChoice as ReceiveDecisionChoiceDB

        user = current_user(info)
        actor_name = resolve_display_name(user["user_id"])
        decision_id = uuid.UUID(str(input.decision_id))
        with SessionLocal() as session:
            warehouse_repository.decide_receive_decision(
                session,
                decision_id,
                ReceiveDecisionChoiceDB(input.decision.value),
                user["user_id"],
                actor_name,
                # Deferred: only a decision with no stamped target needs the caller's GP buyer id,
                # and reaching Clerk for one that has a target would make an outage there refuse a
                # decision that depends on nothing from it.
                lambda: user_repository.get_user_gp_buyer_id(user["user_id"]),
                ADMIN_ROLE in caller_roles(info.context),
            )
            session.commit()
            decision, po, receive_record = _load_decision(session, decision_id)
            return receive_decision_to_type(decision, po, receive_record)

    # Pull Requests - the pick (#367)
    @strawberry.mutation
    def start_pull_request_pick(self, info: strawberry.Info, id: strawberry.ID) -> PullRequest:
        """Claim a pending pull and open it for picking (#367). Nothing moves in inventory.

        This is what `approvePullRequest` used to be, minus everything that touched stock. The
        deduction, the sufficiency question and the consumption of the source request's claim all
        belong to `confirmPick` now, because until somebody has walked the racks nobody knows what
        was picked or from where.

        Open to any signed-in user - it assigns the pull to the caller, so it must not be reachable
        anonymously. The pull is assigned to the Clerk-authenticated caller (#427), never to a name
        the client picks - the assignment is what the whole pick is then attributed to. The old
        `startedBy` argument that let it be picked came out in #438."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            pr = warehouse_repository.start_pull_request_pick(session, uuid.UUID(str(id)), actor)
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, pr.id)
            return pull_request_to_type(pr, partially_picked=False)

    @strawberry.mutation
    def save_pick_draft(
        self,
        info: strawberry.Info,
        pull_request_id: strawberry.ID,
        lines: list[PickLineInput],
    ) -> PickSheet:
        """Save the half-keyed pick sheet without moving anything (#367).

        Replace-all rather than merge: the picker is transcribing a piece of paper, and a save says
        "this is the sheet now". Shape is validated; availability deliberately is not, because a
        draft is a note and blocking it while the numbers are mid-entry would make the button useless
        exactly when it is wanted.

        Open to any signed-in user - it attributes a user action, same rationale as
        `saveAssemblyProgress`. Who entered it is the Clerk-authenticated caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            sheet = warehouse_repository.save_pick_draft(
                session,
                uuid.UUID(str(pull_request_id)),
                _pick_lines_from_input(lines),
                actor,
            )
            # `save_pick_draft` already returns the rebuilt sheet, so it is converted here rather
            # than read a second time: this is the picker's most frequent action, and re-running the
            # whole sheet read over Railway's network hop would double its cost for nothing. Built
            # before the commit, because expire_on_commit would leave the ORM objects detached.
            pr_id = sheet.pull_request.id
            partial = pr_id in warehouse_repository.get_partially_picked_pull_ids(session, [pr_id])
            result = pick_sheet_to_type(sheet, partially_picked=partial)
            session.commit()
            return result

    @strawberry.mutation
    def confirm_pick(
        self,
        info: strawberry.Info,
        pull_request_id: strawberry.ID,
        lines: list[PickLineInput],
    ) -> ConfirmPickResult:
        """Deduct exactly the rows the picker dictated, and consume the claim behind them (#367).

        The atomic swap that used to live in `approvePullRequest`, moved to the moment somebody has
        actually been to the racks: the source request's reservation is consumed for what is being
        picked and those units come off the exact rows named, in one transaction under the pull's
        lock and the locks of every named row.

        No row may give up more than its available units and no combo may exceed what the pull asked
        for - both hard, neither negotiable from the client. A confirmation that does not cover
        everything returns SHORT: what was entered is deducted, the pull stays In Progress and
        un-picked, purchasing is notified once, and a later confirmation enters the remainder.

        Open to any signed-in user - it writes inventory, so it must not be reachable anonymously.
        The deduction is stamped with the Clerk-authenticated caller (#427): this is the audit row
        that says who took the stock off the rack, and it is worth nothing if the client picks the
        name on it."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.confirm_pick(
                session,
                uuid.UUID(str(pull_request_id)),
                _pick_lines_from_input(lines),
                actor,
            )
            notification = notification_to_type(result.notification) if result.notification else None
            shortfalls = [
                InventoryShortfall(
                    hardware_category=s.hardware_category,
                    product_code=s.product_code,
                    requested=s.requested,
                    available=s.available,
                    short=s.short,
                    reserved=s.reserved,
                )
                for s in result.shortfalls
            ]
            outcome = PickOutcome.PICKED if result.outcome == "PICKED" else PickOutcome.SHORT
            applied_quantity = result.applied_quantity
            session.commit()

            pr = warehouse_repository.get_pull_request_details(session, uuid.UUID(str(pull_request_id)))
            partial = (
                pr.id in warehouse_repository.get_partially_picked_pull_ids(session, [pr.id])
                if pr.picked_at is None
                else None
            )
            return ConfirmPickResult(
                pull_request=pull_request_to_type(pr, partially_picked=partial),
                outcome=outcome,
                notification=notification,
                shortfalls=shortfalls,
                applied_quantity=applied_quantity,
            )

    @strawberry.mutation
    def complete_pull_request(self, info: strawberry.Info, id: strawberry.ID) -> PullRequest:
        """Close the whole pull in one go. Since #343 this reads as "stage everything still
        outstanding and finish": any opening not yet confirmed individually is flipped to PULLED and
        stamped here.

        That stamp is the Clerk-authenticated caller as of #427. It was the client's `completedBy`
        string, which made this the clearest example of the bug: one call could put any name on every
        opening the pull staged, and the staging panel shows exactly that name. The argument was
        removed outright in #438."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            pr = warehouse_repository.complete_pull_request(session, uuid.UUID(str(id)), completed_by=actor)
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, pr.id)
            return pull_request_to_type(pr, _partially_picked(session, pr))

    @strawberry.mutation
    def cancel_pull_request(self, info: strawberry.Info, input: CancelPullRequestInput) -> CancelPullRequestResult:
        """Cancel an approved pull, return its hardware to inventory, and hand the source request
        back for re-acceptance (#343).

        All-or-nothing: any opening whose assembly has started or finished refuses the whole
        cancellation with a CONFLICT naming the blockers, because there is nowhere honest to park a
        half-cancelled pull. Everything short of that comes back, staged openings included - their
        hardware is on a cart in the shop, not on a leaf. The source request returns to PENDING and
        its claim is re-created from the returned quantities if availability still allows; if it does
        not, the request is left unreserved and flagged rather than half-claimed.

        Open to any signed-in user - it writes inventory, so it must not be reachable anonymously.
        The cancellation and every restock audit row it writes name the Clerk-authenticated caller
        (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.cancel_pull_request(
                session,
                uuid.UUID(str(input.id)),
                actor,
                input.reason,
            )
            session.commit()
            pr = warehouse_repository.get_pull_request_details(session, result.pull_request.id)
            return CancelPullRequestResult(
                pull_request=pull_request_to_type(pr, partially_picked=_partially_picked(session, pr)),
                restocked=[
                    RestockedLine(
                        hardware_category=r.hardware_category,
                        product_code=r.product_code,
                        quantity=r.quantity,
                    )
                    for r in result.restocked
                ],
                released_opening_ids=[strawberry.ID(str(oid)) for oid in result.released_opening_ids],
                source_request_returned_to_pending=result.source_request_returned_to_pending,
                reservations_recreated=result.reservations_recreated,
                integrity_note=result.integrity_note,
            )

    # Admin Corrections
    @strawberry.mutation
    def adjust_inventory_quantity(
        self,
        info: strawberry.Info,
        inventory_location_id: strawberry.ID,
        adjustment: int,
        reason: str,
        spot_check: bool = False,
    ) -> InventoryLocation:
        """Move a project inventory row's count by a delta, with a reason, writing an ADJUSTMENT
        audit row - or a SPOT_CHECK one when `spot_check` is set (the physical-count reconciliation
        path, whose audit detail also carries systemQuantity/physicalQuantity).

        Every one of those rows said "Admin/Manager" until #427, whoever actually made the change:
        the repository hardcoded it and there was no parameter to pass the truth through. `auditLog`,
        the location history panel and the recent-activity feed all read that column, so the one
        record of who altered a count was uniformly wrong."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.adjust_inventory_quantity(
                session,
                uuid.UUID(str(inventory_location_id)),
                adjustment,
                reason,
                performed_by=actor,
                spot_check=spot_check,
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def override_inventory_quantity(
        self, info: strawberry.Info, input: OverrideInventoryQuantityInput
    ) -> InventoryLocation:
        """Signed-in, not admin. The Correction button on the warehouse Hardware Items tab is
        rendered for everyone ("available to all users, not just admins", HardwareItemsTab.tsx), and it
        opens `InventoryCorrectionModal`, which is what calls this. Admin-gating it would break the
        warehouse's own count-correction workflow.

        Gating it would also buy nothing while `adjustInventoryQuantity` next door stays open to any
        signed-in user: the same end quantity is reachable by passing the delta instead."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.override_inventory_quantity(
                session,
                inv_id=uuid.UUID(str(input.inventory_location_id)),
                new_quantity=input.new_quantity,
                reason=input.reason_text,
                destinations=[
                    {"aisle": d.aisle, "row": d.row, "bay": d.bay, "quantity": d.quantity} for d in input.destinations
                ],
                performed_by=actor,
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def move_inventory_location(
        self,
        info: strawberry.Info,
        inventory_location_id: strawberry.ID,
        new_aisle: str,
        new_row: str,
        new_bay: str,
    ) -> InventoryLocation:
        """Relocate a project inventory row, writing a MOVE audit row naming the caller (#427); it
        used to name "Admin/Manager" regardless of who moved the stock."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.move_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), new_aisle, new_row, new_bay, performed_by=actor
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def mark_inventory_unlocated(
        self, info: strawberry.Info, inventory_location_id: strawberry.ID
    ) -> InventoryLocation:
        """Clear a project inventory row's location, writing an UNLOCATE audit row naming the
        caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.mark_inventory_unlocated(
                session, uuid.UUID(str(inventory_location_id)), performed_by=actor
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def assign_inventory_location(
        self,
        info: strawberry.Info,
        inventory_location_id: strawberry.ID,
        aisle: str,
        row: str,
        bay: str,
    ) -> InventoryLocation:
        """Put a project inventory row away, writing a PUT_AWAY audit row naming the caller (#427)."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            result = warehouse_repository.assign_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), aisle, row, bay, performed_by=actor
            )
            session.commit()
            session.refresh(result)
            return inventory_location_to_type(result)

    @strawberry.mutation
    def split_inventory_location(
        self,
        info: strawberry.Info,
        inventory_location_id: strawberry.ID,
        quantity: int,
    ) -> list[InventoryLocation]:
        """Break units off an inventory row so they can go on a different shelf (#501).

        Put-away happens after approval now, so a receive books one row per PO line and ten hinges
        arriving as one row routinely go to two bins. Returns [original, new] - the new row is
        unlocated and is what the caller then assigns."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            original, remainder = warehouse_repository.split_inventory_location(
                session, uuid.UUID(str(inventory_location_id)), quantity, performed_by=actor
            )
            session.commit()
            session.refresh(original)
            session.refresh(remainder)
            return [inventory_location_to_type(original), inventory_location_to_type(remainder)]

    @strawberry.mutation
    def merge_locations(
        self,
        info: strawberry.Info,
        warehouse_id: strawberry.ID,
        from_aisle: str,
        from_row: str,
        from_bay: str,
        to_aisle: str,
        to_row: str,
        to_bay: str,
    ) -> LocationMergeResult:
        """Admin-gated (#415): rewrites the location of every inventory row and stock item at the
        source location, within one warehouse. warehouse_id is required - a location string is one
        physical place only within a warehouse, so an unscoped merge would rewrite rows that share the
        string in a warehouse the admin never looked at. Its audit rows name the admin who ran it
        (#427) rather than the literal "Admin/Manager" - the gate already proves the role, so the row
        may as well say which admin, given a merge can touch hundreds of rows at once."""
        auth = current_user(info)
        actor = resolve_display_name(auth["user_id"])
        with SessionLocal() as session:
            counts = warehouse_repository.merge_locations(
                session,
                warehouse_id=uuid.UUID(str(warehouse_id)),
                from_aisle=from_aisle,
                from_row=from_row,
                from_bay=from_bay,
                to_aisle=to_aisle,
                to_row=to_row,
                to_bay=to_bay,
                performed_by=actor,
            )
            session.commit()
            return LocationMergeResult(
                inventory_locations=counts["inventory_locations"],
                stock_items=counts["stock_items"],
            )

    # Warehouses (admin)
    @strawberry.mutation
    def create_warehouse(self, info: strawberry.Info, input: CreateWarehouseInput) -> Warehouse:
        with SessionLocal() as session:
            wh = warehouse_admin_repository.create_warehouse(
                session,
                name=input.name,
                code=input.code,
                address=input.address,
                city=input.city,
                province=input.province,
                postal_code=input.postal_code,
                is_primary=input.is_primary,
                is_active=input.is_active,
            )
            session.commit()
            session.refresh(wh)
            return warehouse_to_type(wh)

    @strawberry.mutation
    def update_warehouse(self, info: strawberry.Info, id: strawberry.ID, input: UpdateWarehouseInput) -> Warehouse:
        with SessionLocal() as session:
            wh = warehouse_admin_repository.update_warehouse(
                session,
                uuid.UUID(str(id)),
                name=input.name,
                code=input.code,
                address=input.address,
                city=input.city,
                province=input.province,
                postal_code=input.postal_code,
                is_primary=input.is_primary,
                is_active=input.is_active,
            )
            session.commit()
            session.refresh(wh)
            return warehouse_to_type(wh)

    @strawberry.mutation
    def delete_warehouse(self, info: strawberry.Info, id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            warehouse_admin_repository.delete_warehouse(session, uuid.UUID(str(id)))
            session.commit()
            return True
