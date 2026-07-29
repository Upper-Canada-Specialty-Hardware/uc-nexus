"""Relay installs + live GP reads via the connected relay."""

import logging
import uuid

import strawberry

from app.auth import require_admin, require_user
from app.database import SessionLocal
from app.errors import (
    ConflictError,
    NotFoundError,
    RelayCallError,
    RelayUnavailableError,
    ValidationError,
    validation_error_from_relay,
)
from app.models.relay_install import RelayInstall
from app.repositories import relay_repository
from app.services import relay_adopt
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    gp_buyer_to_type,
    gp_cost_code_to_type,
    gp_customer_address_to_type,
    gp_customer_to_type,
    gp_employee_to_type,
    gp_job_to_type,
    gp_tax_detail_to_type,
    gp_tax_schedule_to_type,
    gp_vendor_to_type,
    relay_install_to_type,
)
from .inputs import EnrollRelayInstallInput
from .types import (
    GpBuyer,
    GpCostCode,
    GpCustomer,
    GpCustomerAddress,
    GpEmployee,
    GpJob,
    GpPoTotals,
    GpTaxDetail,
    GpTaxSchedule,
    GpVendor,
    RelayAdoptWindow,
    RelayEnrollResult,
    RelayInstallInfo,
    RelayInstallProvision,
    RelayStatus,
    VendorCandidate,
    VendorSuggestion,
)

logger = logging.getLogger(__name__)


@strawberry.type
class RelayQueries:
    @strawberry.field
    def relay_installs(self, info: strawberry.Info) -> list[RelayInstallInfo]:
        require_admin(info)
        with SessionLocal() as session:
            return [relay_install_to_type(ri) for ri in relay_repository.list_installs(session)]

    @strawberry.field
    def relay_adopt_window(self, info: strawberry.Info) -> RelayAdoptWindow | None:
        """The currently armed adopt window, or null. Admin-only, and polled by the Relay Installs page
        so the warning banner and its countdown reflect the real (single-replica, in-memory) state
        rather than what the browser that armed it happens to remember."""
        require_admin(info)
        window = relay_adopt.peek()
        if window is None:
            return None
        return RelayAdoptWindow(
            install_id=strawberry.ID(str(window.install_id)),
            label=window.label,
            expires_at=window.expires_at,
            armed_by=window.armed_by,
        )

    @strawberry.field
    def relay_status(self, info: strawberry.Info) -> RelayStatus:
        """Whether the outbound relay WS channel is currently connected (and, if so, the GP company it is
        enrolled for), for the relay status chip and the company-aware PO/receive/adopt dialogs."""
        require_user(info)
        live_install = relay_gateway.install_id
        return RelayStatus(
            connected=relay_gateway.connected,
            company=relay_gateway.company,
            build=relay_gateway.build,
            install_id=strawberry.ID(str(live_install)) if live_install else None,
        )

    @strawberry.field
    async def gp_jobs(self, info: strawberry.Info, company: str) -> list[GpJob]:
        """Live job master (JC00102) via the connected relay."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_jobs")
        return [gp_job_to_type(j) for j in result["jobs"]]

    @strawberry.field
    async def gp_vendors(self, info: strawberry.Info, company: str) -> list[GpVendor]:
        """Live active vendor list (PM00200) via the connected relay."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_vendors")
        return [gp_vendor_to_type(v) for v in result["vendors"]]

    @strawberry.field
    async def gp_buyers(self, info: strawberry.Info, company: str) -> list[str]:
        """Registered GP buyers (POP00101) via the connected relay, for the Create PO buyer dropdown."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_buyers")
        return result["buyers"]

    @strawberry.field
    async def gp_buyers_detailed(self, info: strawberry.Info, company: str) -> list[GpBuyer]:
        """Registered GP buyers (POP00101) WITH their descriptions, via the connected relay, for the
        admin screens that link a Nexus account to a GP buyer identity (#409).

        Admin-gated where gp_buyers above is not, on the same reasoning as gp_employees: the bare id
        list is ordinary working data every PO creator needs, but the descriptions are a staff roster
        by another name ('Don Roberton', and in the production company every buyer's email), and the
        only consumers are admin-only screens."""
        require_admin(info)
        result = await relay_gateway.relay_call(company, "list_buyers_detailed")
        return [gp_buyer_to_type(b) for b in result["buyers"]]

    @strawberry.field
    async def gp_cost_codes(self, info: strawberry.Info, company: str, job: str) -> list[GpCostCode]:
        """Active per-job cost codes (JC00701) via the connected relay, for the Create PO cost-code dropdown."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_cost_codes", {"job": job})
        return [gp_cost_code_to_type(c) for c in result["cost_codes"]]

    @strawberry.field
    async def gp_tax_details(self, info: strawberry.Info, company: str) -> list[GpTaxDetail]:
        """Live GP purchase tax details (TX00201, TXDTLTYP=2) via the connected relay, for the
        register-PO tax-detail dropdown (issue #257)."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_tax_details")
        return [gp_tax_detail_to_type(t) for t in result["tax_details"]]

    @strawberry.field
    async def gp_customers(self, info: strawberry.Info, company: str) -> list[GpCustomer]:
        """Live customer master (RM00101) via the connected relay, for the create-job customer picker
        (#380)."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_customers")
        return [gp_customer_to_type(c) for c in result["customers"]]

    @strawberry.field
    async def gp_customer_addresses(
        self, info: strawberry.Info, company: str, customer: str
    ) -> list[GpCustomerAddress]:
        """One customer's address codes (RM00102) via the connected relay, for the create-job job and
        bill-to address pickers (#380). Scoped to the customer because the job proc validates the codes
        against that customer's addresses."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_customer_addresses", {"customer": customer})
        return [gp_customer_address_to_type(a) for a in result["addresses"]]

    @strawberry.field
    async def gp_employees(self, info: strawberry.Info, company: str) -> list[GpEmployee]:
        """Live payroll employee master (UPR00100) via the connected relay, for the create-job
        estimator and WS manager pickers (#392). The job proc validates both against this master, so
        they cannot be free text.

        Admin-gated, unlike the other gp_* reads. This one returns the payroll roster with names, and
        its only consumer is create_gp_job's dialog, which is already admin-only - so gating it at
        require_user would hand the staff list to every signed-in warehouse and assembly user for no
        benefit. A vendor or customer list is ordinary working data; a payroll master is not."""
        require_admin(info)
        result = await relay_gateway.relay_call(company, "list_employees")
        return [gp_employee_to_type(e) for e in result["employees"]]

    @strawberry.field
    async def gp_tax_schedules(self, info: strawberry.Info, company: str) -> list[GpTaxSchedule]:
        """Live tax schedule master (TX00101) via the connected relay, for the create-job tax-schedule
        and use-tax-schedule pickers (#380). Not gpTaxDetails, which reads TX00201 details."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_tax_schedules")
        return [gp_tax_schedule_to_type(s) for s in result["tax_schedules"]]

    @strawberry.field
    async def gp_divisions(self, info: strawberry.Info, company: str) -> list[str]:
        """WennSoft divisions that have division accounts set up, via the connected relay, for the
        create-job division picker (#380). Bare strings, like gpBuyers: the division code is the only
        label GP has for it."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "list_divisions")
        return result["divisions"]

    @strawberry.field
    async def gp_po_totals(self, info: strawberry.Info, company: str, po_number: str) -> GpPoTotals | None:
        """GP-computed header totals (POP10100) for a PO, read live via the connected relay - auto-fills
        the generated PO document (issue #230). Returns null if the PO isn't found in GP."""
        require_user(info)
        result = await relay_gateway.relay_call(company, "read_po_totals", {"po_number": po_number})
        if result is None or result.get("totals") is None:
            return None
        t = result["totals"]
        return GpPoTotals(
            po_number=t["po_number"],
            subtotal=float(t["subtotal"]),
            freight=float(t["freight"]),
            miscellaneous=float(t["miscellaneous"]),
            tax_amount=float(t["tax_amount"]),
        )

    @strawberry.field
    async def suggest_vendor_for_manufacturer(
        self, info: strawberry.Info, gp_company: str, manufacturer: str
    ) -> VendorSuggestion:
        """Suggest a GP ordering vendor for a hardware line's TITAN manufacturer (issue #232). A saved
        manufacturer->vendor mapping wins (one candidate, score 100, savedMapping true); otherwise the
        live vendor list (PM00200 via the relay) is ranked by fuzzy score and the top candidates are
        returned (savedMapping false). The DB session is scoped to the mapping lookup only, so no
        session is held across the relay round-trip."""
        require_user(info)
        from app.repositories import manufacturer_vendor_map_repository
        from app.services import manufacturer_match

        key = manufacturer_match.normalize(manufacturer)
        # A blank/normalized-empty manufacturer has nothing to look up or rank (lookup returns None,
        # rank_vendors returns []); return empty without the wasted list_vendors relay round-trip.
        if not key:
            return VendorSuggestion(manufacturer=manufacturer, saved_mapping=False, candidates=[])
        with SessionLocal() as session:
            mapping = manufacturer_vendor_map_repository.lookup(session, gp_company, key)
            if mapping is not None:
                return VendorSuggestion(
                    manufacturer=manufacturer,
                    saved_mapping=True,
                    candidates=[
                        VendorCandidate(
                            gp_vendor_id=mapping.gp_vendor_id,
                            gp_vendor_name=mapping.gp_vendor_name,
                            score=100.0,
                        )
                    ],
                )

        result = await relay_gateway.relay_call(gp_company, "list_vendors")
        ranked = manufacturer_match.rank_vendors(manufacturer, result["vendors"])
        return VendorSuggestion(
            manufacturer=manufacturer,
            saved_mapping=False,
            candidates=[
                VendorCandidate(
                    gp_vendor_id=c["gp_vendor_id"],
                    gp_vendor_name=c["gp_vendor_name"],
                    score=c["score"],
                )
                for c in ranked
            ],
        )


@strawberry.type
class RelayMutations:
    @strawberry.mutation
    async def create_gp_buyer(
        self, info: strawberry.Info, buyer_id: str, description: str = "", company: str | None = None
    ) -> GpBuyer:
        """Register a buyer in GP's buyer master through the relay's taCreateBuyer op (#409).

        A Nexus account can only create POs once an admin links it to a GP BUYERID (#216), and until
        now that id had to already exist - so onboarding a new buyer meant opening GP locally to add
        one. This is the same registration GP's Buyer Maintenance window performs.

        `company` defaults to whatever the connected relay is enrolled for, which is the only company
        it could be written to anyway; passing it explicitly is for symmetry with the gp_* reads.

        Admin-only, and writing to the accounting system of record - the same bar create_gp_job sets.
        Note there is no delete counterpart: eConnect exposes no proc for it, and removing a buyer
        rows-deep in POP00101 by hand would bypass the business logic that rule exists to protect."""
        require_admin(info)

        target = company or relay_gateway.company
        if not target:
            raise RelayUnavailableError(
                "The GP relay is not connected, so this buyer cannot be registered in GP. "
                "Start the relay and try again."
            )

        # Bounded here as well as in the relay's CreateBuyerRequest: an over-length id would otherwise
        # travel a full round-trip to come back as a generic invalid_payload, and GP's char widths are
        # the honest thing to report against (BUYERID char(15), taCreateBuyer's DSCRIPTN char(30)).
        cleaned_id = (buyer_id or "").strip()
        if not cleaned_id:
            raise ValidationError("A GP buyer ID is required.", field="buyer_id")
        if len(cleaned_id) > 15:
            raise ValidationError("A GP buyer ID is at most 15 characters.", field="buyer_id")
        cleaned_description = (description or "").strip()
        if len(cleaned_description) > 30:
            raise ValidationError("A GP buyer description is at most 30 characters.", field="description")

        try:
            result = await relay_gateway.relay_call(
                target, "create_buyer", {"buyer_id": cleaned_id, "description": cleaned_description}
            )
        except RelayCallError as e:
            # GP said no, or the id is already registered. Either way the relay words it better than a
            # generic failure would, and the detail body carries the proc + error state the dialog's
            # error alert renders - which is what validation_error_from_relay preserves.
            raise validation_error_from_relay(e) from e

        # GP's stored row, read back from POP00101 by the relay rather than the request echoed back.
        # That row is what gpBuyersDetailed will serve on its next refetch, so answering with anything
        # else could hand the dialog a buyer that differs from the one everything else is about to see.
        return gp_buyer_to_type(
            {
                "buyer_id": str((result or {}).get("buyer_id") or cleaned_id),
                "description": (result or {}).get("description") or None,
            }
        )

    @strawberry.mutation
    def provision_relay_install(self, info: strawberry.Info, label: str, company: str) -> RelayInstallProvision:
        """Admin: create a relay install + a one-time enrollment token shown ONCE. The relay uses the
        token during setup to register its self-generated Bearer secret (which never comes back here)."""
        require_admin(info)
        with SessionLocal() as session:
            install, token = relay_repository.provision_install(session, label=label, company=company)
            session.commit()
            return RelayInstallProvision(
                install_id=strawberry.ID(str(install.id)),
                label=install.label,
                company=install.company,
                enrollment_token=token,
                enrollment_token_expires_at=install.enrollment_token_expires_at,
            )

    @strawberry.mutation
    def arm_relay_adopt(self, info: strawberry.Info, install_id: strawberry.ID) -> RelayAdoptWindow:
        """Admin: open a 5-minute, single-use window in which the next relay connection is accepted
        with WHATEVER secret it presents and bound to this install (#353 PR B).

        This deliberately weakens the /relay-link auth boundary while it is open. It exists because a
        relay whose in-memory secret has drifted from the stored one cannot be recovered any other way
        without physical access to the workstation - and the relay binds localhost, so there is no
        remote restart. Arm it only when a relay you own is dialling in, and disarm as soon as it
        reconnects."""
        identity = require_admin(info)
        with SessionLocal() as session:
            install = session.get(RelayInstall, uuid.UUID(str(install_id)))
            if install is None:
                raise NotFoundError("Relay install not found", field="install_id")
            window = relay_adopt.arm(install_id=install.id, label=install.label, armed_by=identity["user_id"])
        return RelayAdoptWindow(
            install_id=strawberry.ID(str(window.install_id)),
            label=window.label,
            expires_at=window.expires_at,
            armed_by=window.armed_by,
        )

    @strawberry.mutation
    def delete_relay_install(self, info: strawberry.Info, install_id: strawberry.ID) -> bool:
        """Admin: remove a relay install row and revoke its secret (#366).

        Rows pile up from every abandoned provisioning attempt - a token minted and never used, a
        re-enrolment that superseded an earlier row, a retired workstation - and until now the only way
        to remove one was hand-written SQL against Railway Postgres. Two things made that worse than
        clutter: a stale pre-067 row keeps `secret_encrypted` forever, so the count that gated retiring
        RELAY_SECRET_ENC_KEY never reached 0 (that retirement finished in #382); and the row is a live
        credential `authenticate_secret` would still accept.

        Refuses the install currently holding the connection - revoking the credential under a live relay
        would take GP down. A merely switched-off relay deletes fine; that is the retire-a-workstation
        case, and the confirm dialog carries the warning."""
        identity = require_admin(info)
        target = uuid.UUID(str(install_id))
        if relay_gateway.install_id == target:
            raise ConflictError("That relay is currently connected. Disconnect it before removing the install.")
        with SessionLocal() as session:
            snapshot = relay_repository.delete_install(session, target)
            if snapshot is None:
                raise NotFoundError("Relay install not found", field="install_id")
            session.commit()
        # The row is gone, so this log is the only remaining record of it - and revoking a relay
        # credential is exactly the kind of act worth being able to grep for afterwards.
        logger.warning(
            "relay install deleted: %s (label=%s company=%s hostname=%s enrolled_at=%s) by %s",
            snapshot["id"],
            snapshot["label"],
            snapshot["company"],
            snapshot["hostname"],
            snapshot["enrolled_at"],
            identity["user_id"],
        )
        return True

    @strawberry.mutation
    def disarm_relay_adopt(self, info: strawberry.Info) -> bool:
        """Admin: close an open adopt window early. Returns whether one was open."""
        require_admin(info)
        return relay_adopt.disarm()

    @strawberry.mutation
    def enroll_relay_install(self, input: EnrollRelayInstallInput) -> RelayEnrollResult:
        """Called BY THE RELAY during one-time setup, authenticated by the enrollment token (not Clerk).
        Stores the relay's self-generated secret encrypted and consumes the token."""
        with SessionLocal() as session:
            install = relay_repository.enroll_install(
                session,
                enrollment_token=input.enrollment_token,
                hostname=input.hostname,
                secret=input.secret,
            )
            session.commit()
            return RelayEnrollResult(ok=True, install_id=strawberry.ID(str(install.id)))
