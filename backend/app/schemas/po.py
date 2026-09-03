"""Purchase order queries + mutations, including the GP-first write orchestration and PO documents."""

import asyncio
import logging
import uuid
from datetime import date

import strawberry

from app.auth import current_user, resolve_display_name, tenant_scope
from app.database import SessionLocal
from app.errors import (
    GpSetupInvalidError,
    InvalidStateTransitionError,
    NotFoundError,
    RelayUnavailableError,
    ValidationError,
)
from app.models.enums import PODocumentType as PODocumentTypeDB
from app.repositories import (
    buyer_repository,
    po_document_settings_repository,
    po_repository,
    project_repository,
    tenancy,
    user_repository,
)
from app.services import email as email_service
from app.services import gp_idempotency, gp_job_sync, gp_outbox_enqueue, gp_po, gp_po_sync, storage
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    open_po_summary_to_type,
    po_document_settings_to_type,
    po_document_to_type,
    po_line_item_to_type,
    po_list_row_to_type,
    po_to_type,
)
from .enums import PODocumentType, POOrigin, POStatus
from .inputs import (
    CreateDraftPOInput,
    LinkScheduleToMirroredPoInput,
    RegisterPOInput,
    SavePODocumentDataInput,
    UpdatePODocumentSettingsInput,
)
from .types import (
    EmailPoResult,
    GpPoSyncResult,
    LinkScheduleResult,
    OpenPOSummary,
    PODocumentInfo,
    PODocumentSettings,
    POLineItem,
    POStatistics,
    PriorOrderAsForProduct,
    PurchaseOrder,
    PurchaseOrderPage,
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
    scope=None,
    gp_company=None,
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
        # #637: refused as NOT FOUND for a caller outside the PO's company, before anything reaches GP.
        if scope is not None and po.company != scope:
            raise NotFoundError(f"Purchase order {po_id} not found")
        # A PO registers into its own company's GP and no other. Checked here, in the pre-flight, so a
        # mismatch is refused BEFORE the relay push rather than by the persist afterwards - which would
        # leave a PO in GP that Nexus never records.
        if gp_company is not None and (gp_company or "").strip().upper() != po.company:
            raise ValidationError(
                f"This purchase order belongs to {po.company} and cannot be registered in {gp_company}",
                field="gp_company",
            )
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
            # #637: a PO and the job it is raised against belong to one tenant, so a draft can only
            # adopt a project of its own company. Refused before the GP push, not after it.
            if project.company != po.company:
                raise ValidationError(
                    f"Project {project.project_id} belongs to {project.company}, not {po.company}",
                    field="project_id",
                )
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

    # #488: job POs carry the project number as a suffix, so two purchasers registering at the same
    # moment produce visibly distinct, traceable numbers. A stock PO has no project and gets none.
    #
    # GP's PONUMBER is char(17) and 'PO' + 7 digits leaves 7 for '-' + suffix, so a project number
    # over 6 characters cannot fit. That drops the suffix rather than refusing the PO: the suffix is
    # a traceability nicety, and blocking somebody from ordering hardware because their job number
    # is long would be a far worse failure than a PO without it. The relay keeps a hard cap anyway,
    # because a number that reached GP truncated could never be matched back.
    po_number_suffix = job_number or None
    if po_number_suffix and 9 + 1 + len(po_number_suffix) > gp_po._MAX_PO_NUMBER:
        logger.info(
            "Project number %s is too long for a GP PO-number suffix; registering without one",
            po_number_suffix,
        )
        po_number_suffix = None

    gp_po.validate_create_po_inputs(
        job_number=job_number,
        cost_code=cost_code,
        po_number=None,
        line_items=line_items_data,
    )
    payload = gp_po.build_create_po_payload(
        vendor_gp_id=gp_vendor_id,
        vendor_contact_name=None,
        buyer_id=buyer_id,
        job_number=job_number,
        cost_code=cost_code,
        po_number=None,
        line_items=line_items_data,
        po_number_suffix=po_number_suffix,
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
    @strawberry.field(
        deprecation_reason=(
            "Eager-loads every line of every PO, which does not scale to GP's mirrored history. "
            "Use purchaseOrdersPage for the register and purchaseOrder(id) for detail."
        )
    )
    def purchase_orders(
        self, info: strawberry.Info, project_id: strawberry.ID | None = None, status: POStatus | None = None
    ) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            pos = po_repository.get_purchase_orders(session, pid, status, company=scope)
            return [po_to_type(po) for po in pos]

    @strawberry.field
    def po_document_download_url(self, info: strawberry.Info, document_id: strawberry.ID) -> str:
        """Mints a presigned S3 URL, so the gate is the only thing standing between an anonymous
        caller and a supplier PO document (#415)."""
        from app.services import storage

        with SessionLocal() as session:
            tenancy.require_po_document_in_scope(session, uuid.UUID(str(document_id)), tenant_scope(info))
            doc = po_repository.get_po_document(session, uuid.UUID(str(document_id)))
            return storage.generate_presigned_url(doc.s3_key)

    @strawberry.field
    def purchase_orders_page(
        self,
        info: strawberry.Info,
        search: str | None = None,
        statuses: list[POStatus] | None = None,
        origin: POOrigin | None = None,
        project_id: strawberry.ID | None = None,
        sort_field: str = "createdAt",
        sort_dir: str = "desc",
        limit: int = 50,
        offset: int = 0,
    ) -> PurchaseOrderPage:
        """One page of the company-wide register (gp-owned-po mirror). Server-driven paging/search/sort
        so the register scales to GP's full PO history. Rows carry a line_item_count scalar; the detail
        modal loads lines through purchaseOrder(id)."""
        with SessionLocal() as session:
            scope = tenant_scope(info)
            rows, counts, total = po_repository.get_purchase_orders_page(
                session,
                search=search,
                statuses=list(statuses) if statuses else None,
                origin=origin,
                project_id=uuid.UUID(str(project_id)) if project_id else None,
                company=scope,
                sort_field=sort_field,
                sort_dir=sort_dir,
                limit=limit,
                offset=offset,
            )
            # #632: Created By, resolved over the page's DISTINCT author ids (a page of 50 rows has a
            # handful of authors, and resolve_display_name caches per user) rather than per row. A
            # mirrored GP row has no Nexus author, so it shows its GP buyer id instead; a Clerk id
            # that no longer resolves (deleted account) degrades to the raw id rather than failing
            # the whole register page.
            names: dict[str, str] = {}
            for user_id in {r.created_by_user_id for r in rows if r.created_by_user_id}:
                try:
                    names[user_id] = resolve_display_name(user_id)
                except Exception:
                    names[user_id] = user_id

            def _created_by(r) -> str | None:
                if r.created_by_user_id:
                    return names.get(r.created_by_user_id)
                return r.buyer_id or None

            return PurchaseOrderPage(
                rows=[po_list_row_to_type(r, counts.get(r.id, 0), _created_by(r)) for r in rows],
                total_count=total,
            )

    @strawberry.field
    def purchase_order(self, info: strawberry.Info, id: strawberry.ID) -> PurchaseOrder | None:
        with SessionLocal() as session:
            po = po_repository.get_purchase_order(session, uuid.UUID(str(id)), company=tenant_scope(info))
            if po is None:
                return None
            receive_records = po_repository.get_receive_records_for_po(session, po.id)
            return po_to_type(po, receive_records)

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
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            result = po_repository.get_prior_order_as_values(
                session,
                pid,
                product_codes,
                company=scope,
            )
            return [PriorOrderAsForProduct(product_code=pc, values=vals) for pc, vals in result.items()]

    @strawberry.field
    def po_statistics(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> POStatistics:
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            stats = po_repository.get_po_statistics(session, pid, company=scope)
            return POStatistics(
                total=stats["total"],
                draft=stats["draft"],
                gp_registered=stats["gp_registered"],
                vendor_confirmed=stats["vendor_confirmed"],
                partially_received=stats["partially_received"],
                closed=stats["closed"],
                cancelled=stats["cancelled"],
            )

    @strawberry.field(
        deprecation_reason=(
            "Eager-loads every line of every open PO, which does not scale to GP's mirrored history. "
            "Use openPosSummary (lean rows + pending scalars) and poReceivingDetails for detail."
        )
    )
    def open_p_os(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> list[PurchaseOrder]:
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            pos = po_repository.get_open_pos(session, pid, company=scope)
            return [po_to_type(po) for po in pos]

    @strawberry.field
    def open_pos_summary(self, info: strawberry.Info, project_id: strawberry.ID | None = None) -> list[OpenPOSummary]:
        """The receiving picker's open-PO list at company scale (gp-owned-po mirror). Lean rows with two
        pending-quantity scalars from a grouped query, not the line collection."""
        with SessionLocal() as session:
            scope = tenant_scope(info)
            pid = uuid.UUID(str(project_id)) if project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            rows, pending = po_repository.get_open_pos_summary(session, pid, company=scope)
            return [open_po_summary_to_type(r, *(pending.get(r.id, (0, 0)))) for r in rows]

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
    async def sync_gp_pos(self, info: strawberry.Info) -> GpPoSyncResult:
        """Admin: kick the GP PO mirror now, instead of waiting out its own schedule (gp-owned-po
        mirror). This is for seeing the result soon after a PO is created directly in GP, or for
        kicking the first backfill.

        What it does depends on where each company is. A company still BACKFILLING gets a bounded
        batch of history pages inline and reports backfill_done false. A company whose history is
        already mirrored gets its open-book refresh QUEUED - mode 'queued' - and the background loop
        walks it next: that walk is ~94 pages for a company the size of UBC, tens of minutes, which
        would time out at the edge and then race the loop for the same cursor. The loop is the only
        thing that ever walks an open book."""
        # all_companies because somebody pressed a button. The background loop never sweeps - it takes
        # one company per turn and a reconnect does not change that - but "sync now" is expected to
        # look at all of them, and every request inside still draws on the same read budget, so this
        # is slower than a single company rather than heavier on GP.
        result = await gp_po_sync.run_once(backfill_max_pages=gp_po_sync.ADMIN_SYNC_BACKFILL_PAGES, all_companies=True)
        # A queued refresh already woke the loop (request_refresh does it); this covers the backfill
        # half, where the inline batch stopped at its cap and the rest is the loop's to drain.
        if result.get("mode") == "backfill" and not result.get("backfill_done"):
            gp_po_sync.wake()
        return GpPoSyncResult(
            mode=result.get("mode", "incremental"),
            created=result.get("created", 0),
            updated=result.get("updated", 0),
            backfill_done=result.get("backfill_done", False),
        )

    @strawberry.mutation
    def link_schedule_to_mirrored_po(
        self, info: strawberry.Info, input: LinkScheduleToMirroredPoInput
    ) -> LinkScheduleResult:
        """Attach project schedule hardware to a mirrored (GP-origin) PO's lines for coverage tracking
        (gp-owned-po mirror). Marks the named AVAILABLE schedule units IN_PO against the PO line, the
        same linkage a Nexus draft uses. Coverage/reconciliation only - receiving never depends on it.

        Returns linked_units alongside the PO: a typo'd product code, or nothing AVAILABLE at the
        requested qty, links 0 while still returning the PO, so the caller can tell a no-op from a hit
        instead of reading a bare PO as success."""
        links = [
            {
                "po_line_item_id": uuid.UUID(str(link.po_line_item_id)),
                "hardware_category": link.hardware_category,
                "product_code": link.product_code,
                "quantity": link.quantity,
            }
            for link in input.links
        ]
        with SessionLocal() as session:
            tenancy.require_po_in_scope(session, uuid.UUID(str(input.po_id)), tenant_scope(info))
            po, total = po_repository.link_schedule_to_mirrored_po(session, uuid.UUID(str(input.po_id)), links)
            session.commit()
            return LinkScheduleResult(
                linked_units=total,
                purchase_order=po_to_type(po_repository.reload_po(session, po.id)),
            )

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
            scope = tenant_scope(info)
            pid = uuid.UUID(str(input.project_id)) if input.project_id else None
            tenancy.require_project_in_scope(session, pid, scope)
            po = po_repository.create_po(
                session,
                line_items=line_items_data,
                project_id=pid,
                notes=input.notes,
                shipping_cost=input.shipping_cost,
                tariff_amount=input.tariff_amount,
                preferred_delivery_date=input.preferred_delivery_date,
                created_by_user_id=auth["user_id"],
                cost_code=input.cost_code,
                vendor_quote_number=input.vendor_quote_number,
                # A stock PO has no project to take a tenant from, so it takes the caller's. An admin
                # (unscoped) raising one must say which company it is for - `company` on the input.
                company=scope or input.company,
            )
            session.commit()
            return po_to_type(po_repository.reload_po(session, po.id))

    @strawberry.mutation
    async def email_po_to_vendor(self, info: strawberry.Info, po_id: strawberry.ID) -> EmailPoResult:
        """Send the generated supplier PO to the vendor it was placed with (#500).

        The vendor's email is read live from GP through the relay rather than stored: GP owns
        vendors (#509) and Nexus keeps no contact records of its own, so a stale address here is a
        class of bug that cannot happen.

        Every refusal is a plain outcome rather than an exception, because all of them are things
        the user can act on - generate the document, register the PO, ask accounting to put an email
        on the vendor card - and none of them is an error in the sense of "something broke".
        """
        current_user(info)

        with SessionLocal() as session:
            po = po_repository.get_purchase_order(session, uuid.UUID(str(po_id)), company=tenant_scope(info))
            if po is None:
                raise NotFoundError(f"Purchase order {po_id} not found")
            if po.status == POStatus.DRAFT.value or po.gp_vendor_id is None or not po.gp_company:
                return EmailPoResult(sent=False, message="Register the PO in GP before sending it to the vendor.")
            document = next(
                (d for d in (po.documents or []) if d.document_type == PODocumentTypeDB.GENERATED_PO),
                None,
            )
            if document is None:
                return EmailPoResult(sent=False, message="Generate the PO document before sending it to the vendor.")
            po_number = po.po_number or po.request_number
            company = po.gp_company
            vendor_id = po.gp_vendor_id
            s3_key = document.s3_key
            file_name = document.file_name
            content_type = document.content_type

        if not email_service.is_configured():
            return EmailPoResult(sent=False, message="Email is not configured on this deployment.")

        try:
            contact = await relay_gateway.relay_call(company, "get_vendor_contact", {"vendor_id": vendor_id})
        except Exception as exc:  # relay unavailable / timeout / op unsupported
            return EmailPoResult(sent=False, message=f"Could not reach GP for the vendor's email: {exc}")

        address = (contact or {}).get("email")
        if not address:
            return EmailPoResult(
                sent=False,
                message=f"GP has no email on file for vendor {vendor_id}. Ask accounting to add one.",
            )

        contact_name = (contact or {}).get("contact_name") or "there"
        body = (
            f"Hello {contact_name},\n\n"
            f"Please find attached our purchase order {po_number}.\n\n"
            "Reply to this message with your acknowledgement and expected ship date.\n\n"
            "Thank you,\n"
            "UC Hardware Inc."
        )

        try:
            content = storage.download_file(s3_key)
            email_service.send_email(
                to=address,
                subject=f"Purchase Order {po_number}",
                body=body,
                attachments=[email_service.Attachment(file_name=file_name, content_type=content_type, content=content)],
            )
        except email_service.EmailError as exc:
            return EmailPoResult(sent=False, message=f"Sending failed: {exc}")

        return EmailPoResult(sent=True, message=f"Purchase order {po_number} sent to {address}.", sent_to=address)

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
            scope=tenant_scope(info),
            gp_company=input.gp_company,
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
            scope = tenant_scope(info)
            tenancy.require_po_in_scope(session, uuid.UUID(str(id)), scope)
            if pid is not _UNSET:
                tenancy.require_project_in_scope(session, pid, scope)
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
    def update_po_notes(self, info: strawberry.Info, id: strawberry.ID, notes: str | None = None) -> PurchaseOrder:
        """Edit the PO's notes at any status (#632). Notes are a Nexus-only overlay, so the
        receive/status lock `updatePo` enforces on GP-authoritative fields does not apply."""
        with SessionLocal() as session:
            tenancy.require_po_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            po = po_repository.update_po_notes(session, uuid.UUID(str(id)), notes)
            session.commit()
            return po_to_type(po_repository.reload_po(session, po.id))

    @strawberry.mutation
    def cancel_po(self, info: strawberry.Info, id: strawberry.ID) -> PurchaseOrder:
        with SessionLocal() as session:
            tenancy.require_po_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            po = po_repository.cancel_po(session, uuid.UUID(str(id)))
            session.commit()
            session.refresh(po)
            return po_to_type(po)

    @strawberry.mutation
    def update_po_line_item_order_as(
        self, info: strawberry.Info, id: strawberry.ID, order_as: str | None = None
    ) -> POLineItem:
        with SessionLocal() as session:
            tenancy.require_po_line_item_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            poli = po_repository.update_line_item_order_as(session, uuid.UUID(str(id)), order_as)
            session.commit()
            session.refresh(poli)
            return po_line_item_to_type(poli)

    @strawberry.mutation
    def update_po_line_item_unit_cost(self, info: strawberry.Info, id: strawberry.ID, unit_cost: float) -> POLineItem:
        with SessionLocal() as session:
            tenancy.require_po_line_item_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
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
            tenancy.require_po_in_scope(session, uuid.UUID(str(po_id)), tenant_scope(info))
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
            tenancy.require_po_document_in_scope(session, uuid.UUID(str(document_id)), tenant_scope(info))
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
            tenancy.require_po_in_scope(session, pid, tenant_scope(info))
            po_repository.upsert_po_document_data(
                session,
                pid,
                vendor_address=input.vendor_address,
                buyer_name=input.buyer_name,
                currency=input.currency,
                ship_to=input.ship_to,
                shipping_method=input.shipping_method,
                quotation_number=input.quotation_number,
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
