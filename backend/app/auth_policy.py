"""Deny-by-default authorization for every GraphQL root field (#423).

#415 closed a real hole - `updateUserRoles`, the mutation that grants `Admin/Manager`, was reachable
with no session at all - by putting `require_user(info)` / `require_admin(info)` at the top of 161
resolver bodies and policing them with an AST sweep. That worked, and it left three costs:

  - **Opt-in stays opt-in.** A new resolver is public until somebody remembers a line. The AST test
    catches the omission, but only after it is written, and only because the test exists.
  - **The rule was spread across 15 modules.** "Who may call `mergeLocations`" was a line in
    warehouse.py, and answering "what is admin-only" meant grepping.
  - **`require_admin` cost a Clerk Backend API round trip per root field.** Roles are in Clerk
    publicMetadata, not in the session token, so each gate did its own `GET /users/{id}`. The admin
    landing page paid it once per admin query it fired, on top of the JWT verification each gate also
    redid.

This module inverts the default. `ROOT_FIELD_POLICY` below names every root field and what it
requires; `OPEN_OPERATIONS` names the ones deliberately reachable without a Clerk session. A field in
neither is REFUSED - so a resolver shipped without a policy entry fails closed, loudly, instead of
being silently public until someone notices. `enforce_root_field` is called from the schema
extension in main.py, before the resolver runs, so ordering is structural rather than a convention
each body has to honour.

What is deliberately NOT here: `require_admin_request`, the gate for the plain FastAPI routes in
main.py (`/admin/reset-data`, `/testing/clerk-sign-in`). Those are not GraphQL, no extension runs for
them, and they keep their own explicit gate - see app/auth.py.
"""

import logging

from app.auth import (
    ADMIN_ROLE,
    WAREHOUSE_MANAGER_ROLE,
    ForbiddenError,
    authenticated_user_id,
    caller_roles,
    user_roster,
)

logger = logging.getLogger(__name__)

# A signed-in caller with no particular role. Not a Clerk role name, and it cannot collide with one:
# Clerk roles are human-readable strings an admin types into the User Management page, and none of
# them can contain a leading "@" the way this sentinel does.
SIGNED_IN = "@signed-in"

# Root fields whose bodies enumerate the whole Clerk roster anyway (`list_users`, or
# `list_shop_assembly_members` which wraps it). For these the gate answers "what roles does the
# caller hold" out of that one roster call instead of adding its own `GET /users/{id}` - which is the
# `adminStats` double round trip: `require_admin`'s role lookup, then the `list_users` the resolver
# was always going to make, which already carries roles for every user including the caller.
#
# This is a performance hint, NOT an authorization input. The decision of what a field requires is
# ROOT_FIELD_POLICY and only ROOT_FIELD_POLICY; this only picks which Clerk call answers it. Adding a
# field here that does not enumerate users makes it slower, never more permissive.
ROSTER_BACKED = frozenset({"adminStats", "users"})

# Operations reachable without a Clerk session, each with the reason it is safe. This is the whole
# allowlist: everything else is gated, and anything in neither table is refused outright.
OPEN_OPERATIONS: dict[str, str] = {
    # The relay calls this during one-time setup, before it holds any credential, so there is no
    # Clerk session to gate on. It is not unauthenticated: `relay_repository.enroll_install` matches
    # the enrollment token by hash, rejects an expired one, and rejects a reused one via the
    # `enrolled_at` guard. The admin who minted the token is the authorization.
    "enrollRelayInstall": "authenticated by the single-use enrollment token, not Clerk",
}

# Every root field in the schema -> what it requires. SIGNED_IN is any authenticated user; a bare
# string is a Clerk role name the caller must hold; a frozenset is satisfied by ANY ONE of the role
# names in it, for the requirement that is genuinely a choice ("a Warehouse Manager or an admin may
# approve this receive") rather than a single role with an implicit admin bypass - there is no such
# bypass anywhere in this table, and adding one silently would be the more dangerous shorthand.
#
# Grouped by the app/schemas/ module that defines the resolver, queries before mutations within each
# group, so this reads as the same map the modules do. The values were lifted from the gate each
# resolver body called before #423 - this table is that decision, moved, not re-derived.
ROOT_FIELD_POLICY: dict[str, str | frozenset[str]] = {
    # --- admin.py -------------------------------------------------------------------------
    # Both walk a whole project's openings and put purchasing next to fulfilment, which is the
    # admin Opening Status page and nothing else.
    # --- buyer.py -------------------------------------------------------------------------
    # `buyerAssignments` is the PO dialog's read of the CALLER's own row, so any signed-in user;
    # `allBuyerAssignments` is the whole table (which buyer owns which project) and is admin (#428).
    "allBuyerAssignments": ADMIN_ROLE,
    "buyerAssignments": SIGNED_IN,
    "deleteBuyerAssignment": ADMIN_ROLE,
    "saveBuyerAssignment": ADMIN_ROLE,
    # --- custom_items.py ------------------------------------------------------------------
    # The catalog of non-schedule inventory - frames, specialties, consumables (#454). SIGNED_IN
    # throughout: the issue puts maintenance in warehouse users' hands and there is no Clerk role for
    # a plain warehouse user, the reads are consumed by the PO dialog and the inventory screens as
    # well as by the management page, and nothing here moves stock or reaches GP. It is description.
    "inventoryItemTypes": SIGNED_IN,
    "customInventoryItems": SIGNED_IN,
    "createInventoryItemType": SIGNED_IN,
    "updateInventoryItemType": SIGNED_IN,
    "createInventoryItemAttribute": SIGNED_IN,
    "updateInventoryItemAttribute": SIGNED_IN,
    "createCustomInventoryItem": SIGNED_IN,
    "updateCustomInventoryItem": SIGNED_IN,
    # --- dashboard.py ---------------------------------------------------------------------
    "adminStats": ADMIN_ROLE,
    "homeDashboardStats": SIGNED_IN,
    "shopAssemblyStats": SIGNED_IN,
    "shippingStats": SIGNED_IN,
    # --- gp_outbox.py ---------------------------------------------------------------------
    # The two reads feed pending chips on the PO and receiving lists, so any signed-in user. The two
    # writes are admin: retrying an `ambiguous` queued write can duplicate a GP posting, and
    # cancelling one abandons work somebody has already done (#353 PR E).
    "gpOutbox": SIGNED_IN,
    "gpOutboxSummary": SIGNED_IN,
    "cancelGpOutboxEntry": ADMIN_ROLE,
    "retryGpOutboxEntry": ADMIN_ROLE,
    # --- imports.py -----------------------------------------------------------------------
    "projectExcludedItems": SIGNED_IN,
    "projectHardwareSchedule": SIGNED_IN,
    "reconcileSchedule": SIGNED_IN,
    "finalizeImportSession": SIGNED_IN,
    # --- notification.py ------------------------------------------------------------------
    "notifications": SIGNED_IN,
    "markNotificationAsRead": SIGNED_IN,
    # --- po.py ----------------------------------------------------------------------------
    "openPOs": SIGNED_IN,
    "poDocumentDownloadUrl": SIGNED_IN,
    "poDocumentSettings": SIGNED_IN,
    "poStatistics": SIGNED_IN,
    "priorOrderAsValues": SIGNED_IN,
    "purchaseOrder": SIGNED_IN,
    "purchaseOrders": SIGNED_IN,
    "cancelPo": SIGNED_IN,
    "createDraftPo": SIGNED_IN,
    "deletePoDocument": SIGNED_IN,
    # Signed-in, not admin: which projects a caller may raise a PO against is decided inside the
    # resolver from the caller's own GP buyer assignment (#216), not by role.
    "emailPoToVendor": SIGNED_IN,
    "registerPoInGp": SIGNED_IN,
    "savePoDocumentData": SIGNED_IN,
    "updatePo": SIGNED_IN,
    "updatePoDocumentSettings": ADMIN_ROLE,
    "updatePoLineItemOrderAs": SIGNED_IN,
    "updatePoLineItemUnitCost": SIGNED_IN,
    "uploadPoDocument": SIGNED_IN,
    # --- project.py -----------------------------------------------------------------------
    "adminProjects": ADMIN_ROLE,
    "projectByScheduleId": SIGNED_IN,
    "projectShipTo": SIGNED_IN,
    "projects": SIGNED_IN,
    "createGpJob": ADMIN_ROLE,
    "syncGpJobs": ADMIN_ROLE,
    "updateProject": ADMIN_ROLE,
    # --- relay.py -------------------------------------------------------------------------
    # The gp_* reads are signed-in because every PO screen needs them. Three exceptions: two return
    # staff rosters by another name (`gpBuyersDetailed`, buyer ids with names, and `gpEmployees`), and
    # `gpCostCodeMaster` has exactly one consumer, the admin-only create-job dialog, so it sits at the
    # bar the `createGpJob` it feeds already sets. Everything that provisions, adopts or deletes a
    # relay install is admin - those are relay credentials.
    "gpBuyers": SIGNED_IN,
    "gpBuyersDetailed": ADMIN_ROLE,
    "gpCostCodeMaster": ADMIN_ROLE,
    "gpCostCodes": SIGNED_IN,
    "gpCustomerAddresses": SIGNED_IN,
    "gpCustomers": SIGNED_IN,
    "gpDivisions": SIGNED_IN,
    "gpEmployees": ADMIN_ROLE,
    "gpJobs": SIGNED_IN,
    "gpPoTotals": SIGNED_IN,
    "gpTaxDetails": SIGNED_IN,
    "gpTaxSchedules": SIGNED_IN,
    "gpVendors": SIGNED_IN,
    "relayAdoptWindow": ADMIN_ROLE,
    "relayInstalls": ADMIN_ROLE,
    "relayStatus": SIGNED_IN,
    "suggestVendorForManufacturer": SIGNED_IN,
    "armRelayAdopt": ADMIN_ROLE,
    "createGpBuyer": ADMIN_ROLE,
    "createGpCustomerAddress": ADMIN_ROLE,
    "deleteRelayInstall": ADMIN_ROLE,
    "disarmRelayAdopt": ADMIN_ROLE,
    "provisionRelayInstall": ADMIN_ROLE,
    # `enrollRelayInstall` is in OPEN_OPERATIONS above, not here.
    # --- sharepoint_migration.py ----------------------------------------------------------
    # Admin-only on both counts: the query reads another system entirely over the company's Graph
    # credentials, and the mutation writes inventory in bulk with no per-row undo.
    "sharepointInventorySnapshot": ADMIN_ROLE,
    "migrateSharepointInventory": ADMIN_ROLE,
    # --- shipping.py ----------------------------------------------------------------------
    "packingSlips": SIGNED_IN,
    "returnableLines": SIGNED_IN,
    # The staging workspace and its containers (#451). SIGNED_IN like the rest of shipping - the
    # warehouse and the shipping department both load a truck, and neither owns the screen.
    "stagingPool": SIGNED_IN,
    "createShipmentContainer": SIGNED_IN,
    "renameShipmentContainer": SIGNED_IN,
    "deleteShipmentContainer": SIGNED_IN,
    "setContainerItems": SIGNED_IN,
    "confirmShipmentFromContainers": SIGNED_IN,
    # The shipping department's own list of how a load travels (#451). SIGNED_IN like the rest of
    # shipping: it is documentation the same people maintain and consume, and it gates nothing.
    "shipmentMethods": SIGNED_IN,
    "createShipmentMethod": SIGNED_IN,
    "updateShipmentMethod": SIGNED_IN,
    "deleteShipmentMethod": SIGNED_IN,
    "shipReadyItems": SIGNED_IN,
    # Read-only coverage for the shipping-out builder (#451). SIGNED_IN because its caller is the
    # Start-a-Request wizard, which every module's users reach.
    "requestCoverage": SIGNED_IN,
    "shippingOutRequests": SIGNED_IN,
    "acceptShippingOutRequest": SIGNED_IN,
    "confirmShipment": SIGNED_IN,
    "createShipmentReturn": SIGNED_IN,
    # Raising and correcting a request from the Shipping module (#451). SIGNED_IN like the accept
    # beside them: the same people work this board, and both are gated on request state, not role.
    "createShippingOutRequest": SIGNED_IN,
    "editShippingOutRequest": SIGNED_IN,
    "rejectShippingOutRequest": SIGNED_IN,
    "reopenShippingOutRequest": SIGNED_IN,
    # The Delivery Request lifecycle (#447), SIGNED_IN for the same reason confirmShipment is: the
    # shipping department, the warehouse and the office all work the same Shipments page, so no one
    # role's module owns the callers. The lifecycle mutations move nothing - they record where the
    # truck got to - and the edit is refused on state rather than on role.
    "updateShipmentDetails": SIGNED_IN,
    "markShipmentPickedUp": SIGNED_IN,
    "markShipmentDelivered": SIGNED_IN,
    # --- shop_assembly.py -----------------------------------------------------------------
    # `assignOpenings` is SIGNED_IN here on purpose: its role requirement is CONDITIONAL. Anyone may
    # self-assign from the "Assign to me" board; assigning to somebody else is Shop Assembly
    # Manager-only, and that branch cannot be expressed as a field-level requirement, so the body
    # keeps its own `require_role` call for it (#330).
    "shopAssemblyRequests": SIGNED_IN,
    "acceptShopAssemblyRequest": SIGNED_IN,
    "rejectShopAssemblyRequest": SIGNED_IN,
    "reopenShopAssemblyRequest": SIGNED_IN,
    # --- stock.py -------------------------------------------------------------------------
    "deficiencyReviews": SIGNED_IN,
    "deficientItems": SIGNED_IN,
    "stockItem": SIGNED_IN,
    "stockItems": SIGNED_IN,
    "adjustStockQuantity": SIGNED_IN,
    "allocateStockToProject": SIGNED_IN,
    "assignStockItemLocation": SIGNED_IN,
    "destockInventory": SIGNED_IN,
    "markStockItemUnlocated": SIGNED_IN,
    "moveStockLocation": SIGNED_IN,
    "reclassifyStockItem": SIGNED_IN,
    "reportInventoryDeficiency": SIGNED_IN,
    "reportStockDeficiency": SIGNED_IN,
    "resolveDeficiency": SIGNED_IN,
    "transferInventory": SIGNED_IN,
    # --- user.py --------------------------------------------------------------------------
    # All four shipped ungated before #415. `updateUserRoles` is the one that matters most: it grants
    # Admin/Manager, the role every other admin entry in this table is gated on, so an open copy is a
    # self-service escalation into all of them.
    "users": ADMIN_ROLE,
    "updateUserGpBuyerId": ADMIN_ROLE,
    "updateUserName": ADMIN_ROLE,
    "updateUserRoles": ADMIN_ROLE,
    # --- warehouse.py ---------------------------------------------------------------------
    # `overrideInventoryQuantity` is signed-in despite living under an admin-looking component: it is
    # the warehouse's own count correction, not an admin tool.
    "auditLog": SIGNED_IN,
    "backOrderedItems": SIGNED_IN,
    "hardwareStatusByProduct": SIGNED_IN,
    "receives": SIGNED_IN,
    "inventoryRows": SIGNED_IN,
    "locationAuditHistory": SIGNED_IN,
    "locationContents": SIGNED_IN,
    "locationDistinctValues": SIGNED_IN,
    "locationDuplicates": ADMIN_ROLE,
    "locationUtilization": SIGNED_IN,
    "myReceiveDecisions": SIGNED_IN,
    "poReceivingDetails": SIGNED_IN,
    "projectInventoryAvailability": SIGNED_IN,
    "projectProgressByProduct": SIGNED_IN,
    "pullPickSheet": SIGNED_IN,
    "pullRequestDetails": SIGNED_IN,
    "pullRequests": SIGNED_IN,
    "receiveDraft": SIGNED_IN,
    "receiveDrafts": SIGNED_IN,
    "receivingHistoryPos": SIGNED_IN,
    "recentReceiveRecords": SIGNED_IN,
    "unlocatedInventory": SIGNED_IN,
    "warehouse": SIGNED_IN,
    "warehouseDashboard": SIGNED_IN,
    "warehouses": SIGNED_IN,
    "adjustInventoryQuantity": SIGNED_IN,
    # Approving a draft is what posts the GP receipt and credits inventory, so it is the one receiving
    # action that needs a role. Rejecting it is the same authority used the other way. Everything else
    # about a draft - creating, editing, resubmitting, deleting - is SIGNED_IN, because the body
    # decides it from whose draft it is (author, or a manager overriding), which no field-level
    # requirement can express.
    # SIGNED_IN because the requirement is not a property of the field alone since #499: a Warehouse
    # Manager may approve any draft, and the PO creator who answered SHIP_OUT may approve that one
    # draft. `_authorize_draft_approval` in schemas/warehouse.py is the gate, checked against the
    # decision row rather than anything the client sends.
    "approveReceiveDraft": SIGNED_IN,
    "assignInventoryLocation": SIGNED_IN,
    "splitInventoryLocation": SIGNED_IN,
    "cancelPullRequest": SIGNED_IN,
    "completePullRequest": SIGNED_IN,
    "confirmPick": SIGNED_IN,
    "createReceiveDraft": SIGNED_IN,
    "createWarehouse": ADMIN_ROLE,
    "decideReceiveDecision": SIGNED_IN,
    "deleteReceiveDraft": SIGNED_IN,
    "deleteWarehouse": ADMIN_ROLE,
    "markInventoryUnlocated": SIGNED_IN,
    "mergeLocations": ADMIN_ROLE,
    "moveInventoryLocation": SIGNED_IN,
    "overrideInventoryQuantity": SIGNED_IN,
    "rejectReceiveDraft": frozenset({ADMIN_ROLE, WAREHOUSE_MANAGER_ROLE}),
    "resubmitReceiveDraft": SIGNED_IN,
    "savePickDraft": SIGNED_IN,
    "startPullRequestPick": SIGNED_IN,
    "updateReceiveDraft": SIGNED_IN,
    "updateWarehouse": ADMIN_ROLE,
}


def _roles_for(context, field_name: str) -> list[str]:
    """The caller's Clerk roles, taken from whichever call this operation was going to make anyway.

    Both paths are memoised on the request context, so a query hitting several role-gated root fields
    resolves roles once, not once per field."""
    if field_name in ROSTER_BACKED:
        user_id = authenticated_user_id(context)
        for u in user_roster(context):
            if u.get("id") == user_id:
                return u.get("roles") or []
        # The caller is authenticated but absent from the roster Clerk just returned. Fall through to
        # the single-user lookup rather than treating it as "no roles": a fresh account created
        # between the two calls must not be silently demoted.
    return caller_roles(context)


def enforce_root_field(field_name: str, context) -> None:
    """Refuse the caller unless they satisfy this root field's entry in ROOT_FIELD_POLICY.

    Called once per root field (`info.path.prev is None`) by the schema extension in main.py, before
    the resolver runs. Nested fields are never checked: they are only reachable through a root field
    that already was, and checking them would put this on every node of every response.

    Raises AuthError (code UNAUTHENTICATED, which the frontend's Apollo link answers by re-minting
    the Clerk token and replaying once, #429) or ForbiddenError (code FORBIDDEN, which it does not).
    """
    if field_name in OPEN_OPERATIONS:
        return

    requirement = ROOT_FIELD_POLICY.get(field_name)
    if requirement is None:
        # A root field nobody wrote a policy for. Refusing is the whole point of the file: the
        # alternative default - letting it through - is exactly the state #415 had to clean up. The
        # log line is for us, since the caller cannot fix this and the test suite should have.
        logger.error(
            "GraphQL root field %r has no entry in ROOT_FIELD_POLICY and is not in OPEN_OPERATIONS; refusing it",
            field_name,
        )
        raise ForbiddenError(f"'{field_name}' has no authorization policy and cannot be called")

    if requirement == SIGNED_IN:
        authenticated_user_id(context)
        return

    if isinstance(requirement, frozenset):
        # Any one of them satisfies the field. Sorted in the message so the refusal reads the same
        # every time - a set's iteration order is not something an error string should expose.
        if not requirement & set(_roles_for(context, field_name)):
            raise ForbiddenError(f"{' or '.join(sorted(requirement))} role required")
        return

    if requirement not in _roles_for(context, field_name):
        raise ForbiddenError(f"{requirement} role required")
