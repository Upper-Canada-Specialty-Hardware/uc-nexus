"""Purchase order queries + mutations, including the GP-first write orchestration and PO documents."""

import asyncio
import logging
import uuid
from datetime import date

import strawberry

from app.auth import current_user
from app.database import SessionLocal
from app.errors import (
    GpSetupInvalidError,
    InvalidStateTransitionError,
    NotFoundError,
    RelayUnavailableError,
    ValidationError,
)
from app.repositories import (
    buyer_repository,
    po_document_settings_repository,
    po_repository,
    project_repository,
    user_repository,
)
from app.services import gp_idempotency, gp_job_sync, gp_outbox_enqueue, gp_po
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    po_document_settings_to_type,
    po_document_to_type,
    po_line_item_to_type,
    po_to_type,
)
from .enums import PODocumentType, POStatus
from .inputs import CreateDraftPOInput, RegisterPOInput, SavePODocumentDataInput, UpdatePODocumentSettingsInput
from .types import (
    PODocumentInfo,
    PODocumentSettings,
    POLineItem,
    POOpening,
    POOpeningItem,
    POStatistics,
    PriorOrderAsForProduct,
    PurchaseOrder,
    RegisterPOResult,
)

logger = logging.getLogger(__name__)


# --- GP-first write orchestration (issue #202 #1/#3) --------------------------------------------------
# create_po / register_po_in_gp / create_receive (schemas/warehouse.py) push to GP via the relay BEFORE
# persisting, and the two systems are not atomic. Each resolver runs as: idempotency short-circuit ->
# validate eligibility -> relay_call -> record the relay result (own commit) -> persist + stamp the
# record id. The sync DB and Clerk work is offloaded via asyncio.to_thread so no Postgres connection is
# held across the relay round-trip and the event loop running the /relay-link read loop is never
# blocked on a sync call.


def _load_po_type(po_id: uuid.UUID) -> PurchaseOrder:
    with SessionLocal() as session:
        return po_to_type(po_repository.reload_po(session, po_id))


def _po_outbox_identity(po_id: uuid.UUID) -> tuple[uuid.UUID | None, str]:
    """(project_id, label) for a queued register-PO write (#353 PR E).

    project_id routes a terminal failure to a notification; a PO with no project yields None and the
    worker falls back to the queue UI rather than inventing a placeholder project. The label is the
    human line in that queue - a DRAFT being registered has no GP number yet (GP assigns it), so the
    PO's own number, or its id, is the only stable handle. One row, two scalars, one round trip."""
    from sqlalchemy import select

    from app.models.purchase_order import PurchaseOrder as POModel

    with SessionLocal() as session:
        row = session.execute(select(POModel.project_id, POModel.po_number).where(POModel.id == po_id)).first()
    project_id = row.project_id if row is not None else None
    number = row.po_number if row is not None else None
    return project_id, f"Register PO {number or po_id} in GP"


def _resolve_line_manufacturers(session, project_id, line_items_data) -> list[str | None]:
    """Resolve the manufacturer for each payload line from the project's HardwareItem rows, joining on
    (project_id, hardware_category, product_code) - the key line_items_data already carries, so no new
    frontend input (issue #233). Returns a list parallel to line_items_data (None where nothing matches).

    A category+code can map to several imported items; the manufacturer is normally the same across them,
    but if they disagree we take the first non-null (deterministic by created_at, id) and log the conflict
    rather than guessing or failing. No project -> nothing to join against -> all None."""
    if project_id is None:
        return [None] * len(line_items_data)

    from sqlalchemy import select

    from app.models.hardware import HardwareItem

    cache: dict[tuple[str, str], str | None] = {}
    resolved: list[str | None] = []
    for li in line_items_data:
        key = (li["hardware_category"], li["product_code"])
        if key not in cache:
            rows = session.scalars(
                select(HardwareItem.manufacturer)
                .where(
                    HardwareItem.project_id == project_id,
                    HardwareItem.hardware_category == key[0],
                    HardwareItem.product_code == key[1],
                )
                .order_by(HardwareItem.created_at, HardwareItem.id)
            ).all()
            distinct = list(dict.fromkeys(m.strip() for m in rows if m and m.strip()))
            chosen = distinct[0] if distinct else None
            if len(distinct) > 1:
                logger.warning(
                    "manufacturer disagreement for line %s/%s in project %s: %s; using %r",
                    key[0],
                    key[1],
                    project_id,
                    distinct,
                    chosen,
                )
            cache[key] = chosen
        resolved.append(cache[key])
    return resolved


def _assert_buyer_identity(caller_gp_buyer_id: str | None, input_buyer_id: str) -> None:
    """Issue #216: a PO is pushed as the CALLER's GP buyer identity (Clerk publicMetadata.gpBuyerId),
    not a free pick - reject a missing identity or a mismatched buyer_id before anything hits GP."""
    if not caller_gp_buyer_id:
        raise ValidationError(
            "Your account has no GP buyer identity; an Admin must set it in User Management",
            field="buyer_id",
        )
    if (input_buyer_id or "").strip().upper() != caller_gp_buyer_id.strip().upper():
        raise ValidationError("POs can only be created as your own GP buyer", field="buyer_id")


def _prepare_register_po(
    *,
    po_id,
    gp_vendor_id,
    buyer_id,
    cost_code,
    line_items_data,
    tax_detail_id=None,
    shipping_cost=None,
    miscellaneous=None,
    trade_discount=None,
    project_id=None,
) -> dict:
    """Read-only pre-flight for register_po_in_gp: confirm the PO is a registerable DRAFT, resolve the
    job number, pre-validate, and build the relay create_po payload (po_number=None; GP assigns it).
    A lean scalar read - the resolver never needs the PO's documents here."""
    from sqlalchemy import select

    from app.models.enums import POStatus
    from app.models.project import Project as ProjectModel
    from app.models.purchase_order import PurchaseOrder as POModel

    with SessionLocal() as session:
        po = session.scalars(select(POModel).where(POModel.id == po_id, POModel.deleted_at.is_(None))).first()
        if po is None:
            raise NotFoundError(f"Purchase order {po_id} not found")
        if po.status != POStatus.DRAFT:
            raise InvalidStateTransitionError(f"Only a Draft PO can be registered in GP; this one is {po.status.value}")

        # #316: a draft with no project may be given one here, and it has to take effect BEFORE the
        # payload is built - the GP job number and the issue #216 buyer gating both key off it, so
        # validating against the old (absent) project would push the PO to GP under the wrong job.
        # An override is ignored once the PO has a project; the repository enforces the same rule at
        # write time, so the two cannot disagree.
        effective_project_id = po.project_id if po.project_id is not None else project_id

        job_number = None
        if effective_project_id is not None:
            project = session.get(ProjectModel, effective_project_id)
            if project is None:
                raise NotFoundError(f"Project {effective_project_id} not found")
            job_number = project.project_id

        # #425: the stamped quarantine gate. Runs here, in the pre-GP pre-flight, and NOT in
        # po_repository.register_po_in_gp - that one persists after GP has already created the PO, and
        # refusing there would leave a PO in GP that Nexus never records. The resolver re-checks the
        # same job live against GP before the push (see register_po_in_gp); this is the floor that
        # still applies when the live check cannot run.
        project_repository.require_gp_setup_ok(session, effective_project_id)

        # Issue #216: registering a draft is the ordering action - same strict buyer gating.
        buyer_repository.validate_buyer_can_order(session, buyer_id, effective_project_id)

        manufacturers = _resolve_line_manufacturers(session, effective_project_id, line_items_data)

    gp_po.validate_create_po_inputs(
        job_number=job_number, cost_code=cost_code, po_number=None, line_items=line_items_data
    )
    payload = gp_po.build_create_po_payload(
        vendor_gp_id=gp_vendor_id,
        vendor_contact_name=None,
        buyer_id=buyer_id,
        job_number=job_number,
        cost_code=cost_code,
        po_number=None,
        line_items=line_items_data,
        # Issue #257: freight maps from the PO's shipping_cost; misc + trade discount are new inputs.
        tax_detail_id=tax_detail_id,
        freight_amount=shipping_cost,
        misc_amount=miscellaneous,
        trade_discount=trade_discount,
    )
    # build_create_po_payload emits one line per line_items_data entry, in order, so index-align the
    # resolved manufacturers onto the relay payload lines (the relay caps/RTRIMs to USRDEFND1's char(50)).
    for line, manufacturer in zip(payload["lines"], manufacturers):
        line["manufacturer"] = manufacturer
    return payload


def _persist_register_po(
    *,
    key,
    po_id,
    gp_vendor_id,
    vendor_name_snapshot,
    gp_result,
    line_items_data,
    cost_code,
    buyer_id,
    shipping_cost,
    tariff_amount,
    project_id=None,
) -> PurchaseOrder:
    with SessionLocal() as session:
        po_repository.register_po_in_gp(
            session,
            po_id,
            gp_vendor_id=gp_vendor_id,
            vendor_name_snapshot=vendor_name_snapshot,
            po_number=gp_result["po_number"],
            gp_company=gp_result["company"],
            line_items=line_items_data,
            cost_code=cost_code,
            buyer_id=buyer_id,
            shipping_cost=shipping_cost,
            tariff_amount=tariff_amount,
            project_id=project_id,
        )
        gp_idempotency.stamp_result_id(session, key, "register_po_in_gp", gp_result, str(po_id))
        session.commit()
        return po_to_type(po_repository.reload_po(session, po_id))


@strawberry.type
class POQueries:
    @strawberry.field
    def purchase_orders(
        self, info: strawberry.Info, project_id: strawberry.ID | None = None, status: POStatus | None = None
    ) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            pid = uuid.UUID(str(project_id)) if project_id else None
            pos = po_repository.get_purchase_orders(session, pid, status)
            return [po_to_type(po) for po in pos]

    @strawberry.field
    def po_document_download_url(self, info: strawberry.Info, document_id: strawberry.ID) -> str:
        """Mints a presigned S3 URL, so the gate is the only thing standing between an anonymous
        caller and a supplier PO document (#415)."""
        from app.services import storage

        with SessionLocal() as session:
            doc = po_repository.get_po_document(session, uuid.UUID(str(document_id)))
            return storage.generate_presigned_url(doc.s3_key)

    @strawberry.field
    def purchase_order(self, info: strawberry.Info, id: strawberry.ID) -> PurchaseOrder | None:
        with SessionLocal() as session:
            po = po_repository.get_purchase_order(session, uuid.UUID(str(id)))
            if po is None:
                return None
            receive_records = po_repository.get_receive_records_for_po(session, po.id)
            return po_to_type(po, receive_records)

    @strawberry.field
    def po_openings(self, info: strawberry.Info, po_id: strawberry.ID) -> list[POOpening]:
        """Which door openings and leaves this PO's hardware was bought for (#302).

        Its own field rather than a list on PurchaseOrder: the PO list renders dozens of POs and must
        never pay for this join, and the detail modal is the only place it is read."""
        with SessionLocal() as session:
            return [
                POOpening(
                    opening_number=row["opening_number"],
                    leaf=row["leaf"],
                    building=row["building"],
                    floor=row["floor"],
                    location=row["location"],
                    items=[
                        POOpeningItem(
                            hardware_category=i["hardware_category"],
                            product_code=i["product_code"],
                            quantity=i["quantity"],
                        )
                        for i in row["items"]
                    ],
                )
                for row in po_repository.get_po_openings(session, uuid.UUID(str(po_id)))
            ]

    @strawberry.field
    def prior_order_as_values(
        self,
        info: strawberry.Info,
        product_codes: list[str],
        project_id: strawberry.ID | None = None,
    ) -> list[PriorOrderAsForProduct]:
        """What these product codes have been ordered as before ON THIS PROJECT, most recent first,
        so the buyer is offered the job's own alias instead of retyping it (#509).

        Project, not vendor: the vendor that used to scope this was the local contact record, which
        is gone with the table, and the GP vendor is not chosen until register time. Project, not
        global: `order_as` is the GP line's item number, so a global list would offer one supplier's
        catalogue number while raising a PO for another. A null project_id means a stock PO and
        scopes to the other project-less POs."""
        with SessionLocal() as session:
            result = po_repository.get_prior_order_as_values(
                session,
                uuid.UUID(str(project_id)) if project_id else None,
                product_codes,
            )
            return [PriorOrderAsForProduct(product_code=pc, values=vals) for pc, vals in result.items()]

    @strawberry.field
    def po_statistics(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> POStatistics:
        with SessionLocal() as session:
            stats = po_repository.get_po_statistics(session, uuid.UUID(str(project_id)) if project_id else None)
            return POStatistics(
                total=stats["total"],
                draft=stats["draft"],
                gp_registered=stats["gp_registered"],
                vendor_confirmed=stats["vendor_confirmed"],
                partially_received=stats["partially_received"],
                closed=stats["closed"],
                cancelled=stats["cancelled"],
            )

    @strawberry.field
    def open_p_os(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            pos = po_repository.get_open_pos(session, uuid.UUID(str(project_id)) if project_id else None)
            return [po_to_type(po) for po in pos]

    @strawberry.field
    def po_document_settings(self, info: strawberry.Info) -> PODocumentSettings:
        """The admin boilerplate for the generated supplier PO document (issue #230). Signed-in, not
        admin: the PO user's generate form reads it to render the document. Get-or-creates the singleton
        with guideline defaults on first read, so it never returns null."""
        with SessionLocal() as session:
            settings = po_document_settings_repository.get_settings(session)
            session.commit()
            return po_document_settings_to_type(settings)


@strawberry.type
class POMutations:
    @strawberry.mutation
    def create_draft_po(self, info: strawberry.Info, input: CreateDraftPOInput) -> PurchaseOrder:
        """Issue #256: manual PO creation lands as a plain DRAFT - no relay round-trip, no GP fields,
        no buyer involved. Registering the draft into GP (register_po_in_gp) is the separate,
        conscious user action where GP vendor / buyer identity / cost code are captured and the
        issue #216 assignment gating applies.

        The caller is recorded as the request's originator, from the Clerk token rather than an
        argument (#427). A receive against this PO later asks them whether the shipment stays in the
        project's inventory or ships straight out."""
        auth = current_user(info)
        line_items_data = [
            {
                "hardware_category": li.hardware_category,
                "product_code": li.product_code,
                "ordered_quantity": li.ordered_quantity,
                "unit_cost": li.unit_cost,
                "classification": li.classification.value if li.classification else None,
                "order_as": li.order_as,
            }
            for li in input.line_items
        ]
        with SessionLocal() as session:
            po = po_repository.create_po(
                session,
                line_items=line_items_data,
                project_id=uuid.UUID(str(input.project_id)) if input.project_id else None,
                notes=input.notes,
                shipping_cost=input.shipping_cost,
                tariff_amount=input.tariff_amount,
                preferred_delivery_date=input.preferred_delivery_date,
                created_by_user_id=auth["user_id"],
            )
            session.commit()
            return po_to_type(po_repository.reload_po(session, po.id))

    @strawberry.mutation
    async def register_po_in_gp(self, info: strawberry.Info, input: RegisterPOInput) -> RegisterPOResult:
        """Register an imported DRAFT PO into GP (issue #175, the import-acceptance path; brokered
        server-side as of issue #199). Pushes the PO to GP via relay_call (create_po) BEFORE persisting
        anything, then maps the PO to the chosen GP vendor + cost code, replaces the draft's line items
        with the (possibly edited) set that was pushed (assigning gp_line_ord positionally), records GP's
        returned PONUMBER + company, and advances DRAFT -> GP_REGISTERED. The end state is identical to a
        manually created PO. Issue #200: the GP vendor is picked live (gpVendors) and sent as
        gp_vendor_id/gp_vendor_name - there is no local vendor-to-GP mirror to look up anymore.

        Issue #202 #1/#3: idempotency_key makes a retry a no-op in GP; the DRAFT-state guard and fields
        are checked before the relay_call so a double-submit never reaches GP; the DB work is offloaded
        so no Postgres connection is held across the relay round-trip.

        Issue #425 - the two-layer GP setup gate. `_prepare_register_po` applies the STAMPED verdict
        the sync last wrote on the project; this resolver then re-asks GP about that one job LIVE,
        immediately before the push, and that live answer is authoritative. Registering is where the
        damage is done - the WennSoft integration copies the job's cost-code account index onto
        POP10110.INVINDX, and a dangling index there makes a PO that can never be received - so a
        verdict up to a poll interval old is not good enough to let a registration through.

        If the live check cannot run (relay down, relay too old for the op, GP slow), the stamped
        verdict stands and the registration proceeds. That asymmetry is deliberate: the failure being
        defended against is a job that broke in the last few minutes, which is rare, while relays
        restart and flap routinely. Refusing every registration whenever the health op is unreachable
        would trade a rare bad PO for a constantly unusable button - and the relay's own create_po
        pre-check (cost_code_account_invalid) is still there as the last line of defence, running
        inside GP's own transaction where it cannot be stale at all."""
        auth = current_user(info)
        # Issue #216: the PO is registered as the caller's own GP buyer identity, never a free pick.
        caller_buyer = await asyncio.to_thread(user_repository.get_user_gp_buyer_id, auth["user_id"])
        _assert_buyer_identity(caller_buyer, input.buyer_id)
        key = gp_idempotency.validate_key(input.idempotency_key)

        pid = uuid.UUID(str(input.po_id))
        # #316: only meaningful for a draft that has no project; the repository ignores it otherwise.
        register_project_id = uuid.UUID(str(input.project_id)) if input.project_id else None
        line_items_data = [
            {
                "id": str(li.id) if li.id else None,
                "hardware_category": li.hardware_category,
                "product_code": li.product_code,
                "ordered_quantity": li.ordered_quantity,
                "unit_cost": li.unit_cost,
                "classification": li.classification.value if li.classification else None,
                "order_as": li.order_as,
            }
            for li in input.line_items
        ]

        state = await asyncio.to_thread(gp_idempotency.load, key)
        if state is not None and state.result_id is not None:
            po = await asyncio.to_thread(_load_po_type, uuid.UUID(state.result_id))
            return RegisterPOResult(queued=False, outbox_entry_id=None, purchase_order=po)

        payload = await asyncio.to_thread(
            _prepare_register_po,
            po_id=pid,
            gp_vendor_id=input.gp_vendor_id,
            buyer_id=input.buyer_id,
            cost_code=input.cost_code,
            line_items_data=line_items_data,
            tax_detail_id=input.tax_detail_id,
            shipping_cost=input.shipping_cost,
            miscellaneous=input.miscellaneous,
            trade_discount=input.trade_discount,
            project_id=register_project_id,
        )

        # #425 live re-check. The job number is read back off the payload rather than returned
        # separately, because the payload is the thing actually being pushed - checking anything else
        # could check a job this PO is not going to GP under. Only job-cost lines carry one; a
        # non-inventoried PO has no job and nothing to check.
        job_number = next((line["job_number"] for line in payload["lines"] if line.get("job_number")), None)
        if job_number:
            verdict = await gp_job_sync.check_job_setup_live(input.gp_company, job_number)
            if verdict is not None and not verdict.get("ok"):
                issues = [
                    {"cost_code": str(i.get("cost_code") or ""), "account_index": int(i.get("account_index") or 0)}
                    for i in (verdict.get("issues") or [])
                    if isinstance(i, dict)
                ]
                named = ", ".join(f"{i['cost_code']} -> GL account index {i['account_index']}" for i in issues[:3])
                raise GpSetupInvalidError(
                    f"GP job {job_number} is not set up correctly in {input.gp_company}, so this PO "
                    f"cannot be registered: "
                    + (
                        f"these cost codes point at general ledger accounts that do not exist in this company: {named}"
                        if named
                        else "the job has no usable cost codes"
                    )
                    + ". The PO would register but could never be received. Accounting has to correct "
                    "the job's cost-code accounts in GP first.",
                    issues=issues,
                )

        persist_context = {
            "po_id": str(pid),
            "gp_vendor_id": input.gp_vendor_id,
            "vendor_name_snapshot": input.gp_vendor_name,
            "line_items_data": line_items_data,
            "cost_code": input.cost_code,
            "buyer_id": input.buyer_id,
            "shipping_cost": input.shipping_cost,
            "tariff_amount": input.tariff_amount,
            "project_id": str(register_project_id) if register_project_id else None,
        }

        if state is not None and state.relay_result is not None:
            gp_result = state.relay_result
        else:
            try:
                gp_result = await relay_gateway.relay_call(input.gp_company, "create_po", payload)
            except RelayUnavailableError as e:
                # #353 PR E: the relay is unreachable but the job never left the backend, so GP cannot
                # have run it - queue it and tell the user it will post itself. A DISPATCHED failure
                # is re-raised: GP may hold the write, and a blind retry would reserve a second PO
                # number.
                if not gp_outbox_enqueue.may_enqueue(e):
                    raise
                project_id, label = await asyncio.to_thread(_po_outbox_identity, pid)
                entry_id = await asyncio.to_thread(
                    gp_outbox_enqueue.enqueue,
                    idempotency_key=key,
                    op="register_po_in_gp",
                    relay_op="create_po",
                    company=input.gp_company,
                    payload=payload,
                    persist_context=persist_context,
                    entity_key=f"po:{pid}",
                    label=label,
                    project_id=project_id,
                    requested_by=auth["user_id"],
                )
                # The PO is still DRAFT; the list shows it as queued until the worker drains it.
                po = await asyncio.to_thread(_load_po_type, pid)
                return RegisterPOResult(queued=True, outbox_entry_id=strawberry.ID(entry_id), purchase_order=po)
            await asyncio.to_thread(gp_idempotency.record_relay_result, key, "register_po_in_gp", gp_result)

        po = await asyncio.to_thread(
            _persist_register_po,
            key=key,
            po_id=pid,
            gp_vendor_id=input.gp_vendor_id,
            vendor_name_snapshot=input.gp_vendor_name,
            gp_result=gp_result,
            line_items_data=line_items_data,
            cost_code=input.cost_code,
            buyer_id=input.buyer_id,
            shipping_cost=input.shipping_cost,
            tariff_amount=input.tariff_amount,
        )
        return RegisterPOResult(queued=False, outbox_entry_id=None, purchase_order=po)

    @strawberry.mutation
    def update_po(
        self,
        info: strawberry.Info,
        id: strawberry.ID,
        expected_delivery_date: date | None = None,
        preferred_delivery_date: date | None = None,
        po_number: str | None = None,
        vendor_quote_number: str | None = None,
        project_id: strawberry.ID | None = None,
        notes: str | None = None,
        # Issue #156: tri-state (omitted / null / value) - null clears, 0 is a valid entered value.
        shipping_cost: float | None = strawberry.UNSET,
        tariff_amount: float | None = strawberry.UNSET,
    ) -> PurchaseOrder:
        from app.repositories.po_repository import _UNSET

        pid = uuid.UUID(str(project_id)) if project_id else _UNSET
        with SessionLocal() as session:
            po = po_repository.update_po(
                session,
                uuid.UUID(str(id)),
                expected_delivery_date=expected_delivery_date,
                preferred_delivery_date=preferred_delivery_date,
                po_number=po_number,
                vendor_quote_number=vendor_quote_number,
                project_id=pid,
                notes=notes,
                shipping_cost=_UNSET if shipping_cost is strawberry.UNSET else shipping_cost,
                tariff_amount=_UNSET if tariff_amount is strawberry.UNSET else tariff_amount,
            )
            session.commit()
            return po_to_type(po_repository.reload_po(session, po.id))

    @strawberry.mutation
    def mark_po_as_ordered(self, info: strawberry.Info, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.mark_po_as_ordered(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(po)
            return po_to_type(po)

    @strawberry.mutation
    def cancel_po(self, info: strawberry.Info, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            po = po_repository.cancel_po(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(po)
            return po_to_type(po)

    @strawberry.mutation
    def update_po_line_item_order_as(
        self, info: strawberry.Info, id: strawberry.ID, order_as: str | None = None
    ) -> POLineItem:
        with SessionLocal() as session:
            poli = po_repository.update_line_item_order_as(session, uuid.UUID(str(id)), order_as)
            session.commit()
            session.refresh(poli)
            return po_line_item_to_type(poli)

    @strawberry.mutation
    def update_po_line_item_unit_cost(self, info: strawberry.Info, id: strawberry.ID, unit_cost: float) -> POLineItem:
        with SessionLocal() as session:
            poli = po_repository.update_line_item_unit_cost(session, uuid.UUID(str(id)), unit_cost)
            session.commit()
            session.refresh(poli)
            return po_line_item_to_type(poli)

    # PO Documents
    @strawberry.mutation
    def upload_po_document(
        self,
        info: strawberry.Info,
        po_id: strawberry.ID,
        file_name: str,
        content_type: str,
        document_type: PODocumentType,
        file_data_base64: str,
    ) -> PODocumentInfo:
        from app.models.enums import PODocumentType as PODocTypeDB

        with SessionLocal() as session:
            doc = po_repository.upload_po_document(
                session,
                uuid.UUID(str(po_id)),
                file_name,
                content_type,
                PODocTypeDB(document_type.value),
                file_data_base64,
            )
            session.commit()
            session.refresh(doc)
            return po_document_to_type(doc)

    @strawberry.mutation
    def delete_po_document(self, info: strawberry.Info, document_id: strawberry.ID) -> bool:
        with SessionLocal() as session:
            po_repository.delete_po_document(session, uuid.UUID(str(document_id)))
            session.commit()
            return True

    @strawberry.mutation
    def update_po_document_settings(
        self, info: strawberry.Info, input: UpdatePODocumentSettingsInput
    ) -> PODocumentSettings:
        """Patch the single-row PO-document boilerplate (issue #230). Admin-only. Only fields the client
        actually sent (not UNSET) are written, so a partial edit leaves the rest intact."""
        fields = {
            name: getattr(input, name)
            for name in (
                "tax_numbers",
                "mandatory_bullets",
                "shipping_accounts",
                "shipping_methods",
                "customs_broker_block",
                "fsc_note",
                "usa_tariff_note",
                "usa_tariff_effective_until",
                "company_from_address",
                "payment_terms",
                "confirm_with",
                "footer_notes",
                "signature_note",
            )
            if getattr(input, name) is not strawberry.UNSET
        }
        with SessionLocal() as session:
            settings = po_document_settings_repository.update_settings(session, **fields)
            session.commit()
            session.refresh(settings)
            return po_document_settings_to_type(settings)

    @strawberry.mutation
    def save_po_document_data(
        self, info: strawberry.Info, po_id: strawberry.ID, input: SavePODocumentDataInput
    ) -> PurchaseOrder:
        """Persist the generate-dialog capture for a PO (issue #230) and return the PO with its now-saved
        documentData, so a re-open of the dialog pre-fills. Signed-in (any PO user generates)."""
        pid = uuid.UUID(str(po_id))
        with SessionLocal() as session:
            po_repository.upsert_po_document_data(
                session,
                pid,
                vendor_address=input.vendor_address,
                buyer_name=input.buyer_name,
                currency=input.currency,
                ship_to=input.ship_to,
                shipping_method=input.shipping_method,
                proposal_number=input.proposal_number,
                freight=input.freight,
                miscellaneous=input.miscellaneous,
                tax_amount=input.tax_amount,
                tax_label=input.tax_label,
                tariff_amount=input.tariff_amount,
                required_by_override=input.required_by_override,
                include_fsc=input.include_fsc,
                include_usa_tariff=input.include_usa_tariff,
                include_customs=input.include_customs,
            )
            session.commit()
            po = po_repository.get_purchase_order(session, pid)
            receive_records = po_repository.get_receive_records_for_po(session, pid)
            return po_to_type(po, receive_records)
