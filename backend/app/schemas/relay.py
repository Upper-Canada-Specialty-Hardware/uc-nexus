"""Relay installs + live GP reads via the connected relay."""

import logging
import uuid

import strawberry

from app.auth import require_admin, require_user
from app.database import SessionLocal
from app.errors import ConflictError, NotFoundError
from app.models.relay_install import RelayInstall
from app.repositories import relay_repository
from app.services import relay_adopt
from app.services.relay_gateway import gateway as relay_gateway

from .converters import (
    gp_cost_code_to_type,
    gp_job_to_type,
    gp_tax_detail_to_type,
    gp_vendor_to_type,
    relay_install_to_type,
)
from .inputs import EnrollRelayInstallInput
from .types import (
    GpCostCode,
    GpJob,
    GpPoTotals,
    GpTaxDetail,
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
