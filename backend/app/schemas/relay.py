"""Relay installs + live GP reads via the connected relay."""

import logging
import uuid

import strawberry

from app.auth import current_user, tenant_scope
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
from app.repositories import relay_event_repository, relay_repository
from app.services import preview_registry, relay_adopt
from app.services import relay_gateway as relay_gateway_module
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    gp_buyer_to_type,
    gp_cost_code_master_entry_to_type,
    gp_cost_code_to_type,
    gp_customer_address_to_type,
    gp_customer_to_type,
    gp_employee_to_type,
    gp_job_to_type,
    gp_tax_detail_to_type,
    gp_tax_schedule_to_type,
    gp_vendor_to_type,
    relay_event_to_type,
    relay_install_to_type,
)
from .inputs import CreateGpCustomerAddressInput, EnrollRelayInstallInput
from .types import (
    GpBuyer,
    GpCostCode,
    GpCostCodeMasterEntry,
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
    RelayEvent,
    RelayInstallInfo,
    RelayInstallProvision,
    RelayStatus,
    VendorCandidate,
    VendorSuggestion,
)

logger = logging.getLogger(__name__)

# Every field of a GP customer address, as (input attribute, GraphQL field, label, GP column width,
# required). The widths are taCreateCustomerAddress's own parameter widths - char(15) CUSTNMBR /
# ADRSCODE, char(60) ADDRESS1 / ADDRESS2 / COUNTRY, char(35) CITY, char(29) STATE, char(10) ZIPCODE -
# and the required four are what make the row an address anyone could ship hardware to.
#
# The GraphQL name is carried alongside because that is what the error's `field` extension has to be
# for a dialog to anchor the message to the input the user typed it into; the resolver's own argument
# names are snake_case and mean nothing to the client.
_GP_ADDRESS_FIELDS = (
    ("customer_number", "customerNumber", "A GP customer number", 15, True),
    ("address_code", "addressCode", "An address code", 15, True),
    ("address1", "address1", "A street address", 60, True),
    ("address2", "address2", "A second address line", 60, False),
    ("city", "city", "A city", 35, True),
    ("state", "state", "A state or province", 29, False),
    ("zip_code", "zipCode", "A postal or ZIP code", 10, False),
    ("country", "country", "A country", 60, False),
)


def _sole_relay_company() -> str:
    """The connected relay's company when it serves exactly one, for the two GP writes that predate
    multi-company and take no company of their own (#637).

    An install serving several has no default and says so: guessing which GP company a buyer or a
    customer address is written into is not a mistake that can be undone from here."""
    available = relay_gateway.companies
    if len(available) == 1:
        return available[0]
    if not available:
        raise RelayUnavailableError(
            "The GP relay is not connected, so this cannot be written to GP. Start the relay and try again."
        )
    raise ValidationError(
        f"The connected relay serves several GP companies ({', '.join(available)}); name the one to use.",
        field="company",
    )


def resolve_gp_company(info: strawberry.Info, company: str) -> str:
    """The GP company a passthrough read may actually be made for (#637).

    Two gates, and both matter. The relay one is old: a company the live install does not serve fails
    every read anyway, so refusing here turns a 30s round trip into a message naming what IS available.
    The tenant one is new: `gpJobs(company: "UCSH")` is a read of another company's job master, and
    nothing about the relay stops a UCSH-less user asking for it - only the caller's own scope does.
    Admin/Manager is unscoped and may ask for any company the relay serves."""
    requested = relay_gateway_module.normalize_company(company)
    if not requested:
        raise ValidationError("A GP company is required.", field="company")

    available = relay_gateway.companies
    if not available:
        raise RelayUnavailableError(
            "The GP relay is not connected, so GP cannot be read. Start the relay and try again."
        )
    if requested not in available:
        raise ValidationError(
            f"The connected relay does not serve {requested}. It is enrolled for {', '.join(available)}.",
            field="company",
        )

    scope = tenant_scope(info)
    if scope is not None and requested != scope:
        raise ValidationError(f"Your account can only read GP company {scope}.", field="company")
    return requested


@strawberry.type
class RelayQueries:
    @strawberry.field
    def relay_installs(self, info: strawberry.Info) -> list[RelayInstallInfo]:
        with SessionLocal() as session:
            return [relay_install_to_type(ri) for ri in relay_repository.list_installs(session)]

    @strawberry.field
    def relay_adopt_window(self, info: strawberry.Info) -> RelayAdoptWindow | None:
        """The currently armed adopt window, or null. Admin-only, and polled by the Relay Installs page
        so the warning banner and its countdown reflect the real (single-replica, in-memory) state
        rather than what the browser that armed it happens to remember."""
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
        """Whether the outbound relay WS channel is currently connected (and, if so, the GP companies it
        is enrolled for), for the relay status chip and the company-aware PO/receive/adopt dialogs.

        Answered entirely from the gateway's in-memory state plus the preview registry - no database
        read at all. This is polled by every open tab, so it has to stay cheap enough to be, and the
        gateway is the only thing that can be right about a live socket anyway (#654)."""
        live_install = relay_gateway.install_id
        return RelayStatus(
            connected=relay_gateway.connected,
            companies=relay_gateway.companies,
            build=relay_gateway.build,
            install_id=strawberry.ID(str(live_install)) if live_install else None,
            last_connected_at=relay_gateway.last_connected_at,
            last_disconnected_at=relay_gateway.last_disconnected_at,
            last_disconnect_reason=relay_gateway.last_disconnect_reason,
            configured_companies=relay_gateway.configured_companies,
            preview_channels=preview_registry.channels(),
        )

    @strawberry.field
    def relay_events(self, info: strawberry.Info, limit: int = 50) -> list[RelayEvent]:
        """The relay connection history, newest first (#654).

        Admin-only, exactly like `relayInstalls`: these rows name installs, builds and refused
        credentials, which is relay-credential territory rather than working data."""
        capped = max(1, min(limit, 500))
        with SessionLocal() as session:
            return [relay_event_to_type(e) for e in relay_event_repository.list_events(session, capped)]

    @strawberry.field
    async def gp_jobs(self, info: strawberry.Info, company: str) -> list[GpJob]:
        """Live job master (JC00102) via the connected relay."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_jobs")
        return [gp_job_to_type(j) for j in result["jobs"]]

    @strawberry.field
    async def gp_vendors(self, info: strawberry.Info, company: str) -> list[GpVendor]:
        """Live active vendor list (PM00200) via the connected relay."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_vendors")
        return [gp_vendor_to_type(v) for v in result["vendors"]]

    @strawberry.field
    async def gp_buyers(self, info: strawberry.Info, company: str) -> list[str]:
        """Registered GP buyers (POP00101) via the connected relay, for the Create PO buyer dropdown."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_buyers")
        return result["buyers"]

    @strawberry.field
    async def gp_buyers_detailed(self, info: strawberry.Info, company: str) -> list[GpBuyer]:
        """Registered GP buyers (POP00101) WITH their descriptions, via the connected relay, for the
        admin screens that link a Nexus account to a GP buyer identity (#409).

        Admin-gated where gp_buyers above is not, on the same reasoning as gp_employees: the bare id
        list is ordinary working data every PO creator needs, but the descriptions are a staff roster
        by another name ('Don Roberton', and in the production company every buyer's email), and the
        only consumers are admin-only screens."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_buyers_detailed")
        return [gp_buyer_to_type(b) for b in result["buyers"]]

    @strawberry.field
    async def gp_cost_codes(self, info: strawberry.Info, company: str, job: str) -> list[GpCostCode]:
        """Active per-job cost codes (JC00701) via the connected relay, for the Create PO cost-code dropdown."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_cost_codes", {"job": job})
        return [gp_cost_code_to_type(c) for c in result["cost_codes"]]

    @strawberry.field
    async def gp_cost_code_master(
        self, info: strawberry.Info, company: str, division: str
    ) -> list[GpCostCodeMasterEntry]:
        """GP's cost code master (JC40202) for one division, via the connected relay - the create-job
        dialog's cost-code picker (#448).

        Not gpCostCodes, which reads the codes already on a job (JC00701). wsiJCJobMaster creates a job
        with none of those at all, so this is the list a new job's codes are chosen FROM, and the pick
        is provisioned in the same GP transaction as the job.

        Scoped to a division because that is what decides whether a code is usable at all: the GL
        account comes from JC40302's (division, cost element) mapping, and a code the division has no
        usable account for comes back mapped=false for the picker to render disabled rather than hide.
        Hiding it would leave the user hunting for a code they can see in GP; disabling it says the
        division is what needs fixing."""
        result = await relay_gateway.relay_call(
            resolve_gp_company(info, company), "list_cost_code_master", {"division": division}
        )
        return [gp_cost_code_master_entry_to_type(c) for c in result["cost_codes"]]

    @strawberry.field
    async def gp_tax_details(self, info: strawberry.Info, company: str) -> list[GpTaxDetail]:
        """Live GP purchase tax details (TX00201, TXDTLTYP=2) via the connected relay, for the
        register-PO tax-detail dropdown (issue #257)."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_tax_details")
        return [gp_tax_detail_to_type(t) for t in result["tax_details"]]

    @strawberry.field
    async def gp_customers(self, info: strawberry.Info, company: str) -> list[GpCustomer]:
        """Live customer master (RM00101) via the connected relay, for the create-job customer picker
        (#380)."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_customers")
        return [gp_customer_to_type(c) for c in result["customers"]]

    @strawberry.field
    async def gp_customer_addresses(
        self, info: strawberry.Info, company: str, customer: str
    ) -> list[GpCustomerAddress]:
        """One customer's address codes (RM00102) via the connected relay, for the create-job job and
        bill-to address pickers (#380). Scoped to the customer because the job proc validates the codes
        against that customer's addresses."""
        result = await relay_gateway.relay_call(
            resolve_gp_company(info, company), "list_customer_addresses", {"customer": customer}
        )
        return [gp_customer_address_to_type(a) for a in result["addresses"]]

    @strawberry.field
    async def gp_employees(self, info: strawberry.Info, company: str) -> list[GpEmployee]:
        """Live payroll employee master (UPR00100) via the connected relay, for the create-job
        estimator and WS manager pickers (#392). The job proc validates both against this master, so
        they cannot be free text.

        Admin-gated, unlike the other gp_* reads. This one returns the payroll roster with names, and
        its only consumer is create_gp_job's dialog, which is already admin-only - so gating it at
        merely signed-in would hand the staff list to every warehouse and assembly user for no
        benefit. A vendor or customer list is ordinary working data; a payroll master is not."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_employees")
        return [gp_employee_to_type(e) for e in result["employees"]]

    @strawberry.field
    async def gp_tax_schedules(self, info: strawberry.Info, company: str) -> list[GpTaxSchedule]:
        """Live tax schedule master (TX00101) via the connected relay, for the create-job tax-schedule
        and use-tax-schedule pickers (#380). Not gpTaxDetails, which reads TX00201 details."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_tax_schedules")
        return [gp_tax_schedule_to_type(s) for s in result["tax_schedules"]]

    @strawberry.field
    async def gp_divisions(self, info: strawberry.Info, company: str) -> list[str]:
        """WennSoft divisions that have division accounts set up, via the connected relay, for the
        create-job division picker (#380). Bare strings, like gpBuyers: the division code is the only
        label GP has for it."""
        result = await relay_gateway.relay_call(resolve_gp_company(info, company), "list_divisions")
        return result["divisions"]

    @strawberry.field
    async def gp_po_totals(self, info: strawberry.Info, company: str, po_number: str) -> GpPoTotals | None:
        """GP-computed header totals (POP10100) for a PO, read live via the connected relay - auto-fills
        the generated PO document (issue #230). Returns null if the PO isn't found in GP."""
        result = await relay_gateway.relay_call(
            resolve_gp_company(info, company), "read_po_totals", {"po_number": po_number}
        )
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

        result = await relay_gateway.relay_call(resolve_gp_company(info, gp_company), "list_vendors")
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

        `company` defaults to the connected relay's single company, which since #637 only holds when
        the install serves exactly one - an install serving several has no default and the caller must
        say which, because writing a buyer into the wrong GP company is not a recoverable mistake.

        Admin-only, and writing to the accounting system of record - the same bar create_gp_job sets.
        Note there is no delete counterpart: eConnect exposes no proc for it, and removing a buyer
        rows-deep in POP00101 by hand would bypass the business logic that rule exists to protect."""

        target = resolve_gp_company(info, company or _sole_relay_company())

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
    async def create_gp_customer_address(
        self, info: strawberry.Info, input: CreateGpCustomerAddressInput
    ) -> GpCustomerAddress:
        """Add an address code to a GP customer through the relay's taCreateCustomerAddress op (#444).

        The create-job dialog picks its job and bill-to addresses out of gpCustomerAddresses, and the
        job proc validates both against that customer's own addresses - so a site GP had never been
        told about meant abandoning the dialog, opening GP to add the address, and starting over. This
        is the write half of that picker, and its only consumer.

        `input.company` is optional and falls back to the relay's single company, which is unambiguous
        only while the install serves exactly one (#637). The create-job dialog this feeds chooses a
        company explicitly and should send the same one.

        Nothing is persisted in Nexus. The address lives in GP, and gpCustomerAddresses is how it comes
        back - which is why the answer here is GP's own stored row rather than the input echoed back.

        Admin-only, and creating only: the relay pins taCreateCustomerAddress's UpdateIfExists to 0, so
        this can never overwrite an address accounting maintains in GP.
        """

        company = resolve_gp_company(info, input.company or _sole_relay_company())

        # Trimmed and bounded here as well as in the relay's CreateCustomerAddressRequest, for the
        # reason create_gp_buyer gives above: the relay's model is the server-side truth, but it can
        # only report a rejection as a whole pydantic dump after a full round-trip, with no field for a
        # dialog to anchor it to. The dialog checks these too, so what this catches is a caller that
        # isn't the dialog - and GP's own char widths are the honest thing to report against.
        cleaned: dict[str, str | None] = {}
        for attr, gql_field, label, limit, required in _GP_ADDRESS_FIELDS:
            value = (getattr(input, attr) or "").strip()
            if attr == "address_code":
                # Uppercased here as well as in the relay's model. GP's own codes are uppercase
                # ('MAIN', 'PRIMARY'), so this is what lands in RM00102 either way - doing it on this
                # side too means the payload this backend logs is the row GP stores rather than
                # whatever case the value happened to be typed in.
                value = value.upper()
            if required and not value:
                raise ValidationError(f"{label} is required.", field=gql_field)
            if len(value) > limit:
                raise ValidationError(f"{label} is at most {limit} characters in GP.", field=gql_field)
            # An untouched optional stays absent rather than becoming a blank string, so the relay is
            # never guessing at what the user left empty.
            cleaned[attr] = value if required else (value or None)

        payload = {
            "customer": cleaned["customer_number"],
            "address_code": cleaned["address_code"],
            "address1": cleaned["address1"],
            "address2": cleaned["address2"],
            "city": cleaned["city"],
            "state": cleaned["state"],
            "zip_code": cleaned["zip_code"],
            "country": cleaned["country"],
        }

        try:
            result = await relay_gateway.relay_call(company, "create_customer_address", payload)
        except RelayCallError as e:
            # GP said no - a customer that does not exist, a code already on this customer, a value GP
            # will not take. The relay words those better than a generic failure would, and the detail
            # body carries the proc + error state the dialog's error alert renders, which is what
            # validation_error_from_relay preserves.
            raise validation_error_from_relay(e) from e

        # GP's stored row, read back from RM00102 by the relay. That row is what gpCustomerAddresses
        # will serve on its next refetch, so answering with anything else could hand the dialog an
        # address that differs from the one it is about to see in the picker.
        #
        # Subscripted bare, with no fallback to the input: a relay whose response shape has drifted
        # must fail here, loudly, the way every sibling resolver does. Falling back would answer with
        # the caller's own values dressed up as GP's stored row - a well-formed success reporting an
        # address nobody has confirmed landed, which is exactly the echo the docstring forbids.
        return gp_customer_address_to_type(result["address"])

    @strawberry.mutation
    def provision_relay_install(self, info: strawberry.Info, label: str, companies: list[str]) -> RelayInstallProvision:
        """Admin: create a relay install + a one-time enrollment token shown ONCE. The relay uses the
        token during setup to register its self-generated Bearer secret (which never comes back here).

        `companies` is every GP company this install may be called for (#637) - the relay's own
        allowed_companies list, recorded on the backend side. Non-empty, each code uppercased and
        bounded at GP's char(15)."""
        with SessionLocal() as session:
            install, token = relay_repository.provision_install(session, label=label, companies=companies)
            session.commit()
            return RelayInstallProvision(
                install_id=strawberry.ID(str(install.id)),
                label=install.label,
                companies=list(install.companies),
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
        identity = current_user(info)
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
        identity = current_user(info)
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
            "relay install deleted: %s (label=%s companies=%s hostname=%s enrolled_at=%s) by %s",
            snapshot["id"],
            snapshot["label"],
            snapshot["companies"],
            snapshot["hostname"],
            snapshot["enrolled_at"],
            identity["user_id"],
        )
        return True

    @strawberry.mutation
    def disarm_relay_adopt(self, info: strawberry.Info) -> bool:
        """Admin: close an open adopt window early. Returns whether one was open."""
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
