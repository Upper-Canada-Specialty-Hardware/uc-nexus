"""Project queries + mutations."""

import asyncio
import logging
import uuid

import strawberry

from app.auth import tenant_scope
from app.database import SessionLocal
from app.errors import (
    ConflictError,
    NotFoundError,
    RelayCallError,
    RelayUnavailableError,
    validation_error_from_relay,
)
from app.repositories import project_repository, tenancy
from app.services import gp_job_sync
from app.services.relay_gateway import gateway as relay_gateway

from .converters import project_to_type
from .inputs import CreateGpJobInput, UpdateProjectInput
from .relay import resolve_gp_company
from .types import (
    AdminProjectDetail,
    CreateGpJobResult,
    GpJobSyncResult,
    POStatusCount,
    Project,
    ProjectShipTo,
)

logger = logging.getLogger(__name__)


def _load_project(job_number: str, company: str) -> Project:
    with SessionLocal() as session:
        project = project_repository.get_project_by_schedule_id(session, job_number, company=company)
        if project is None:
            raise NotFoundError(f"Project {job_number} not found")
        return project_to_type(project)


async def _adopt_existing(job_number: str, company: str) -> Project:
    """Make sure a job GP already holds has its Nexus project, and return it.

    Runs a full sync pass rather than adopting the one job: the pass reads GP's own job master, so the
    project gets GP's name rather than whatever the caller typed, and it is the same code path that
    would have created this project a few minutes later anyway."""
    await gp_job_sync.run_once()
    return await asyncio.to_thread(_load_project, job_number.strip(), company)


@strawberry.type
class ProjectQueries:
    @strawberry.field
    def projects(self, info: strawberry.Info) -> list[Project]:
        """The project picker every module reads, so signed-in rather than the admin requirement on
        `admin_projects` below - same rows, fewer fields.

        Archived projects are excluded here and only here (#637): this is the list that decides what a
        user can start new work against, and a finished job should stop appearing in it without any of
        its existing POs, inventory or shipments changing behaviour."""
        with SessionLocal() as session:
            rows = project_repository.list_projects_with_opening_counts(
                session, company=tenant_scope(info), include_archived=False
            )
            return [project_to_type(p, include_openings=False, opening_count=count) for p, count in rows]

    @strawberry.field
    def admin_projects(self, info: strawberry.Info) -> list[Project]:
        """Admin/Manager-only project list with all editable fields for the admin Projects page.

        Includes archived rows - the page is where archiving is undone, so hiding them would make an
        archived project unreachable - and spans every company, because Admin/Manager is unscoped."""
        with SessionLocal() as session:
            rows = project_repository.list_projects_with_opening_counts(
                session, company=tenant_scope(info), include_archived=True
            )
            return [project_to_type(p, include_openings=False, opening_count=count) for p, count in rows]

    @strawberry.field
    def project_by_schedule_id(self, info: strawberry.Info, project_id: str) -> Project | None:
        with SessionLocal() as session:
            p = project_repository.get_project_by_schedule_id(session, project_id, company=tenant_scope(info))
            if p is None:
                return None
            return project_to_type(p)

    @strawberry.field
    def admin_project_detail(self, info: strawberry.Info, id: strawberry.ID) -> AdminProjectDetail | None:
        """What the admin Projects page shows when a row is opened (#637) - the project plus the three
        rollups that answer "is anything still live on this job" before somebody archives it."""
        with SessionLocal() as session:
            detail = project_repository.get_admin_project_detail(session, uuid.UUID(str(id)))
            if detail is None:
                return None
            return AdminProjectDetail(
                project=project_to_type(detail["project"], include_openings=False),
                po_counts_by_status=[
                    POStatusCount(status=status, count=count) for status, count in detail["po_counts_by_status"]
                ],
                inventory_on_hand=detail["inventory_on_hand"],
                open_shipping_request_count=detail["open_shipping_request_count"],
            )

    @strawberry.field
    def project_ship_to(self, info: strawberry.Info, project_id: strawberry.ID) -> ProjectShipTo | None:
        """The job-site address block for a project, by its UUID - the "deliver to site" ship-to option
        on the generated PO document (issue #230). A lean projection, kept off the PO list query."""
        with SessionLocal() as session:
            p = project_repository.get_project(session, uuid.UUID(str(project_id)), company=tenant_scope(info))
            if p is None:
                return None
            return ProjectShipTo(
                id=strawberry.ID(str(p.id)),
                project_id=p.project_id,
                job_site_name=p.job_site_name,
                address=p.address,
                city=p.city,
                state=p.state,
                zip=p.zip,
            )


@strawberry.type
class ProjectMutations:
    @strawberry.mutation
    async def create_gp_job(self, info: strawberry.Info, input: CreateGpJobInput) -> CreateGpJobResult:
        """Originate a job in GP, then hold it as a UC Nexus project (#380).

        This replaces the old adopt_gp_job mutation. Adoption is no longer something a user does: the
        gp_job_sync service creates a project for every job GP reports, so a manual adopt dialog could
        only ever land on "already adopted". What was missing was the other direction - Nexus could
        take a job GP already had, but could not originate one.

        GP goes first and there is no outbox fallback, unlike the PO and receive writes. Two reasons:
        the form cannot even be composed without live GP reads (customer, address codes, tax schedule
        and division all come from GP, the same gating the register-PO dialog applies), so a queued
        submit could never have been assembled while the relay was down; and a failed submit costs
        nothing to retry from the still-open dialog. Queuing would buy latency tolerance nobody needs
        and add an ambiguous-write class that does not otherwise exist here.

        The selected cost codes are provisioned in the SAME GP transaction as the job (#448), because
        the proc alone leaves JC00701 empty - a job with no cost codes has an empty register-PO
        dropdown and is quarantined by the #425 setup check on the next sync stamp. Splitting them
        into a second call would make that broken state reachable through a partial failure.

        `cost_codes_provisioned` carries how many of them GP actually kept, so the dialog can be honest
        about a selection that did not land. On the adopt path it is zero and means it: an already
        existing job is left exactly as GP has it, the picked codes are NOT applied to it, and
        created=false plus the zero count is how the client is told that.

        Admin-only. Creating a job writes to the accounting system of record.

        `input.company` names the GP company the job is created in and becomes the project's tenant
        (#637). It is validated against the connected relay's enrolled companies and, for a non-admin
        caller, against their own - though this field is admin-gated, so the second check only ever
        matters if the policy is loosened later.
        """

        company = resolve_gp_company(info, input.company)

        payload = {
            "job_number": input.job_number,
            "job_name": input.job_name,
            "division": input.division,
            "customer_number": input.customer_number,
            "job_address_code": input.job_address_code,
            "billto_address_code": input.billto_address_code,
            "tax_schedule_id": input.tax_schedule_id,
            "created_date": input.created_date.isoformat(),
            "estimator_id": input.estimator_id,
            "ws_manager_id": input.ws_manager_id,
            "ws_project_number": input.ws_project_number,
            "bill_customer_number": input.bill_customer_number,
            "use_tax_schedule": input.use_tax_schedule,
            "schedule_start_date": input.schedule_start_date.isoformat() if input.schedule_start_date else None,
            "scheduled_completion_date": (
                input.scheduled_completion_date.isoformat() if input.scheduled_completion_date else None
            ),
            "bid_due_date": input.bid_due_date.isoformat() if input.bid_due_date else None,
            # Only the code number and its element travel (#448). Everything else the JC00701 row
            # needs - alias, description, and the GL account index above all - the relay reads out of
            # GP's own master inside the same transaction, so nothing here can dictate an account.
            "cost_codes": [
                {"cost_code": c.cost_code.strip(), "cost_element": c.cost_element} for c in input.cost_codes
            ],
        }

        try:
            result = await relay_gateway.relay_call(company, "create_job", payload)
        except RelayCallError as e:
            if (e.detail or {}).get("error") == "job_already_exists":
                # GP has the job but we were not the ones who put it there, OR we were and the reply
                # was lost (a relay_call timeout after the proc committed). Either way the invariant
                # this feature exists to hold - a job in GP is a project in Nexus - is satisfiable
                # right now, so satisfy it instead of dead-ending the dialog on an error that no
                # amount of retrying can clear.
                logger.info("create_gp_job: %s already in GP; adopting instead", input.job_number)
                project = await _adopt_existing(input.job_number, company)
                # Nothing was provisioned: the create never ran, and this path deliberately does not
                # go on to write cost codes onto a job somebody else's setup already owns.
                return CreateGpJobResult(project=project, created=False, cost_codes_provisioned=0)
            # GP said no - a closed fiscal period, an address code that isn't on the customer, a
            # division without accounts. The proc words those better than we could, so the message is
            # passed through to the dialog rather than replaced with a generic failure.
            raise validation_error_from_relay(e) from e

        # GP's own record of what it created, read back from JC00102 by the relay - not the input
        # echoed back (see ops.create_job_op).
        job_number = str((result or {}).get("job_number") or input.job_number).strip()
        job_name = str((result or {}).get("job_name") or input.job_name).strip() or None
        # The relay's verified read-back of JC00701, not len(payload["cost_codes"]). A relay older than
        # #448 ignores the unknown cost_codes key entirely and answers without this field, so it reads
        # as 0 - which is exactly what happened in GP, and how a silently dropped selection surfaces to
        # the dialog instead of being reported as a provisioned job.
        cost_codes_provisioned = int((result or {}).get("cost_codes_provisioned") or 0)

        def _persist() -> Project:
            with SessionLocal() as session:
                project = project_repository.adopt_gp_job(
                    session, job_number=job_number, job_name=job_name, company=company
                )
                session.commit()
                session.refresh(project)
                return project_to_type(project)

        try:
            # Off the event loop: the /relay-link read loop runs on it and must not block on Postgres.
            return CreateGpJobResult(
                project=await asyncio.to_thread(_persist),
                created=True,
                cost_codes_provisioned=cost_codes_provisioned,
            )
        except ConflictError:
            # The sync adopted this job between GP committing and us persisting. Benign race, same as
            # the one _persist_missing swallows from the other side - the row we wanted exists.
            # GP still created the job on this call, so this is a real creation - only the Nexus row
            # was written by someone else first.
            logger.info("create_gp_job: %s was adopted by the sync first", job_number)
            return CreateGpJobResult(
                project=await asyncio.to_thread(_load_project, job_number, company),
                created=True,
                cost_codes_provisioned=cost_codes_provisioned,
            )
        except Exception:
            # The job EXISTS in GP at this point - that call already committed. Losing the Nexus row is
            # recoverable rather than fatal: the sync adopts it on its next pass, and retrying the
            # dialog now lands on the job_already_exists path above. Still an error to the caller,
            # because the project is not there yet when the dialog closes.
            logger.exception("create_gp_job: GP created %s but the project persist failed", job_number)
            raise

    @strawberry.mutation
    async def sync_gp_jobs(self, info: strawberry.Info) -> GpJobSyncResult:
        """Admin: run one pass of the GP job sync now, instead of waiting out the poll interval.

        The background service already does this on a timer and on every relay reconnect, so this is
        for the case where someone wants to see the result immediately - after creating a job directly
        in GP, or when checking whether the sync is working at all."""
        total, adopted = await gp_job_sync.run_once()
        return GpJobSyncResult(total=total, adopted=adopted)

    @strawberry.mutation
    async def update_project(self, info: strawberry.Info, id: strawberry.ID, input: UpdateProjectInput) -> Project:
        """Edit a project, and tell GP about the parts GP holds too (#497).

        The job name and the site address live in both systems. Correcting them in Nexus alone left
        GP with the old ones, and GP is what purchasing, accounting and the printed PO read - so the
        wrong address reached the vendor long after somebody had fixed it here.

        Nexus commits first and pushes second, deliberately. The edit is the user's and must not be
        lost to a GP outage; the push is a replication of it. When the relay is unreachable the push
        goes on the outbox and drains later, which is the same shape every other GP write in this
        codebase uses. A GP refusal is surfaced - the edit is already saved, so there is nothing to
        roll back and nothing the user can do about the GP half except be told.
        """
        with SessionLocal() as session:
            tenancy.require_project_in_scope(session, uuid.UUID(str(id)), tenant_scope(info))
            project = project_repository.update_project(
                session,
                uuid.UUID(str(id)),
                description=input.description,
                client=input.client,
                job_site_name=input.job_site_name,
                address=input.address,
                city=input.city,
                state=input.state,
                zip=input.zip,
                contractor=input.contractor,
                project_manager=input.project_manager,
                application=input.application,
                gc_contact_name=input.gc_contact_name,
                gc_phone=input.gc_phone,
                gc_email=input.gc_email,
                off_site_storage_agreement=input.off_site_storage_agreement,
            )
            session.commit()
            session.refresh(project)
            pushed = _gp_site_payload(project)
            project_type = project_to_type(project)
            quarantined = project.gp_setup_ok is False
            # Read inside the session, beside the payload: the push targets the PROJECT's own GP
            # company (#637), not "the connected relay's company", which no longer identifies one.
            company = project.company

        if pushed is not None and not quarantined:
            await _push_site_to_gp(uuid.UUID(str(id)), pushed, company)
        return project_type

    @strawberry.mutation
    def set_project_archived(self, info: strawberry.Info, id: strawberry.ID, archived: bool) -> Project:
        """Hide a project from the picker every module reads, or bring it back (#637).

        Admin-only, and deliberately the whole of what archiving does: nothing about the project's POs,
        inventory, pull requests or shipments changes. It is a decision about what people can START new
        work against, not a lifecycle state."""
        with SessionLocal() as session:
            project = project_repository.set_project_archived(session, uuid.UUID(str(id)), archived)
            session.commit()
            session.refresh(project)
            return project_to_type(project, include_openings=False)


def _gp_site_payload(project) -> dict | None:
    """What of this project GP holds, or None when there is nothing to push.

    Only the job name and the site address: they are the fields that exist on both sides. Everything
    else on the project - the GC contact, the estimator, the storage agreement - is Nexus's alone, and
    sending it would mean inventing a place to put it in GP.

    An address is a street and a city or it is nothing GP can ship to, so a half-filled one is not
    pushed rather than written as a partial record.
    """
    name = (project.description or "").strip()
    address1 = (project.address or "").strip()
    city = (project.city or "").strip()
    has_address = bool(address1 and city)
    if not name and not has_address:
        return None

    payload: dict = {"job_number": project.project_id}
    if name:
        payload["job_name"] = name
    if has_address:
        payload["address1"] = address1
        payload["city"] = city
        payload["state"] = (project.state or "").strip()
        payload["zip_code"] = (project.zip or "").strip()
    return payload


async def _push_site_to_gp(project_id: uuid.UUID, payload: dict, company: str) -> None:
    """Replicate the edit onto the GP job, queueing it if the relay never took it.

    `company` is the PROJECT's own (#637). It used to be whatever single company the relay was
    connected for, which was the same thing only while there was exactly one - now it would push one
    company's job edit against another company's GP database.

    Only an UNDISPATCHED relay failure queues (`should_enqueue`): the write never left the backend, so
    GP cannot be holding it. Anything ambiguous - a dispatched disconnect, a timeout - is NOT queued,
    because a second push of the same values would mint nothing new but would still be a write against
    accounting data on a guess.
    """
    from app.services import gp_outbox_enqueue

    if not company:
        logger.info("update_project: project has no GP company, skipping the site push")
        return

    try:
        await relay_gateway.relay_call(company, "update_job_site", payload)
    except RelayUnavailableError as e:
        if not gp_outbox_enqueue.should_enqueue(e):
            logger.warning("update_project: site push for %s failed ambiguously: %s", payload["job_number"], e)
            return
        gp_outbox_enqueue.enqueue(
            # Keyed on the values, so re-saving the same edit while it is queued is one entry, and a
            # genuinely different correction queues as its own. Company-qualified since #637: a job
            # number is only unique within a company, so without it two companies editing their own
            # job 1001 to the same address would collapse into one queued write.
            idempotency_key=(
                f"update_job_site:{company}:{payload['job_number']}:{hash(tuple(sorted(payload.items())))}"
            ),
            op="update_job_site",
            relay_op="update_job_site",
            company=company,
            payload=payload,
            persist_context={},
            entity_key=f"project:{project_id}",
            label=f"Site details for job {payload['job_number']}",
            project_id=project_id,
        )
    except RelayCallError as e:
        # GP refused - an address code collision, a job it does not have. The edit is already saved
        # in Nexus, so this is reported rather than raised: failing the mutation would tell the user
        # their correction did not happen when it did.
        logger.warning("update_project: GP refused the site push for %s: %s", payload["job_number"], e)
