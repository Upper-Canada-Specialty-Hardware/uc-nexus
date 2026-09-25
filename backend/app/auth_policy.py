"""Deny-by-default authorization for every GraphQL root field (#423).

#415 closed a real hole - `updateUserRoles`, the mutation that grants the roles every other entry in
this table is gated on, was reachable with no session at all - by putting
`require_user(info)` / `require_admin(info)` at the top of 161
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
    DB_ADMIN_ROLE,
    NEXUS_ADMIN_ROLE,
    PO_MANAGERS,
    SHIPPING_MANAGERS,
    SHOP_ASSEMBLY_MANAGERS,
    TENANT_OWNERS,
    WAREHOUSE_MANAGERS,
    ForbiddenError,
    authenticated_user_id,
    caller_roles,
    remember_roster_entry,
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
ROSTER_BACKED = frozenset({"adminStats", "users", "postgresAdmins", "postgresAccessAudit"})

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
# names in it, for the requirement that is genuinely a choice ("a Warehouse Manager, a TENANT OWNER
# or a UC NEXUS ADMIN may reject this receive") rather than a single role with an implicit admin
# bypass - there is no such bypass anywhere in this table, and adding one silently would be the more
# dangerous shorthand. The tier sets from app/auth.py (TENANT_OWNERS, WAREHOUSE_MANAGERS,
# SHOP_ASSEMBLY_MANAGERS, PO_MANAGERS, SHIPPING_MANAGERS) are those any-of sets named once, so a row
# reads as the ruling it came from rather than as a repeated set literal.
#
# Grouped by the app/schemas/ module that defines the resolver, queries before mutations within each
# group, so this reads as the same map the modules do. The values were lifted from the gate each
# resolver body called before #423 - this table is that decision, moved, not re-derived.
ROOT_FIELD_POLICY: dict[str, str | frozenset[str]] = {
    # --- admin.py -------------------------------------------------------------------------
    # Both walk a whole project's openings and put purchasing next to fulfilment, which is the
    # admin Opening Status page and nothing else.
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
    # The Tenant Owner landing's counts. TENANT_OWNERS rather than the cross-tenant role (#729):
    # the figures are about one company's own hardware, openings and people, and the resolver scopes
    # all three by `tenant_scope`.
    "adminStats": TENANT_OWNERS,
    "homeDashboardStats": SIGNED_IN,
    "shopAssemblyStats": SIGNED_IN,
    "shippingStats": SIGNED_IN,
    # --- db_access.py ---------------------------------------------------------------------
    # The tier ABOVE UC Nexus Admin (db-admin-postgres-access). Every field here mints, lists,
    # rotates or revokes internet-reachable read-write Postgres logins, so unlike the rest of the
    # UC Nexus Admin module these name DB_ADMIN_ROLE and admit no one else - there is no admin
    # bypass in this table. The repository refuses all five again when the feature is disabled (no
    # proxy / a preview env).
    "postgresAdmins": DB_ADMIN_ROLE,
    "postgresAccessAudit": DB_ADMIN_ROLE,
    "mintPostgresAdmin": DB_ADMIN_ROLE,
    "rotatePostgresAdmin": DB_ADMIN_ROLE,
    "revokePostgresAdmin": DB_ADMIN_ROLE,
    # --- gp_outbox.py ---------------------------------------------------------------------
    # The two reads feed pending chips on the PO and receiving lists, so any signed-in user.
    #
    # The two writes are SIGNED_IN at the table and decided in the body instead (#729): a held write
    # belongs to whoever raises that kind of work - a held PO REGISTRATION to the people who raise
    # POs, a held GP RECEIVE ENTRY to the people who approve receives - so the requirement is a
    # property of the ENTRY, not of the field, which is the one case this table cannot express. The
    # body loads the entry, refuses it outside the caller's company, and then applies the set for
    # its op. Retrying an `ambiguous` queued write can still duplicate a GP posting, so the sets are
    # the module's managers and the people who own that write, never everyone signed in.
    "gpOutbox": SIGNED_IN,
    "gpOutboxSummary": SIGNED_IN,
    "cancelGpOutboxEntry": SIGNED_IN,
    "retryGpOutboxEntry": SIGNED_IN,
    # --- gp_sync_state.py -----------------------------------------------------------------
    # The Nexus half of NEXUS GP TRAFFIC (#679): what the GP sync loops are doing right now, per
    # company, plus the GP READ LIMIT balance and the PENDING GP WRITES counts. Operations rather than
    # work, it spans every company at once, and it names the relay build and install - so it sits
    # with the other relay reads at the cross-tenant role.
    "gpSyncState": NEXUS_ADMIN_ROLE,
    # --- imports.py -----------------------------------------------------------------------
    "projectExcludedItems": SIGNED_IN,
    "projectHardwareSchedule": SIGNED_IN,
    "projectOpenings": SIGNED_IN,
    "reconcileSchedule": SIGNED_IN,
    "finalizeImportSession": SIGNED_IN,
    # --- inventory_value.py ---------------------------------------------------------------
    # What everything in the building is worth (#662). A company-wide dollar figure and the door
    # counts behind it, so not a shop-floor read - but the Shop Assembly Manager is the person who
    # actually knows how many doors are standing in the building, which is why the writes are theirs
    # as well as the tenant owners'.
    "inventoryValue": SHOP_ASSEMBLY_MANAGERS,
    "inventoryValueCompanies": SHOP_ASSEMBLY_MANAGERS,
    "saveDoorsOnHand": SHOP_ASSEMBLY_MANAGERS,
    "removeDoorsOnHand": SHOP_ASSEMBLY_MANAGERS,
    "setAverageDoorCost": SHOP_ASSEMBLY_MANAGERS,
    # --- notification.py ------------------------------------------------------------------
    "notifications": SIGNED_IN,
    "markNotificationAsRead": SIGNED_IN,
    # --- po.py ----------------------------------------------------------------------------
    "openPOs": SIGNED_IN,
    # Lean company-scale receiving picker list (gp-owned-po mirror).
    "openPosSummary": SIGNED_IN,
    "poDocumentDownloadUrl": SIGNED_IN,
    "poDocumentSettings": SIGNED_IN,
    "poStatistics": SIGNED_IN,
    "priorOrderAsValues": SIGNED_IN,
    "purchaseOrder": SIGNED_IN,
    "purchaseOrders": SIGNED_IN,
    # Server-paginated register over the whole company (gp-owned-po mirror).
    "purchaseOrdersPage": SIGNED_IN,
    "cancelPo": SIGNED_IN,
    "createDraftPo": SIGNED_IN,
    # Give a GP-born PO's lines their schedule identity - the NEXUS REGISTERED LINE write.
    "nexusRegisterPoLines": SIGNED_IN,
    "deletePoDocument": SIGNED_IN,
    # Signed-in, not admin: raising and registering a PO is ordinary purchasing work, and the PO is
    # pushed as the caller's own GP buyer identity, which the resolver enforces.
    "emailPoToVendor": SIGNED_IN,
    "registerPoInGp": SIGNED_IN,
    # GP-PROCESSING, the read-back the register dialog waits on. Signed-in for the same reason
    # registering is: it is the second half of one ordinary purchasing action, on the caller's own PO.
    "runGpProcessing": SIGNED_IN,
    "savePoDocumentData": SIGNED_IN,
    "updatePo": SIGNED_IN,
    "updatePoNotes": SIGNED_IN,
    # The PO module's own settings - what the generated PO document says and looks like. PO MANAGER
    # owns them (#729), with the tenant owners beside them as an any-of.
    "updatePoDocumentSettings": PO_MANAGERS,
    "updatePoLineItemOrderAs": SIGNED_IN,
    "updatePoLineItemUnitCost": SIGNED_IN,
    "uploadPoDocument": SIGNED_IN,
    # --- project.py -----------------------------------------------------------------------
    # The Tenant Owner module's Projects page, so TENANT_OWNERS throughout (#729) - every one of
    # these is about one company's own jobs. `adminProjectDetail` sits at the same bar as
    # `adminProjects`: it is the other half of that page, and its three rollups span a project's
    # whole purchasing, inventory and shipping state. `setProjectArchived` decides what every
    # module's picker offers. `createGpJob` writes to the accounting system of record.
    "adminProjectDetail": TENANT_OWNERS,
    "adminProjects": TENANT_OWNERS,
    "projectByScheduleId": SIGNED_IN,
    "projectShipTo": SIGNED_IN,
    "projects": SIGNED_IN,
    "createGpJob": TENANT_OWNERS,
    "setProjectArchived": TENANT_OWNERS,
    "syncGpJobs": TENANT_OWNERS,
    # SIGNED_IN, unlike its job-sync neighbour (#744): pulling the PO mirror up to date is something
    # everyone who works the PO table needs, and the resolver scopes the pass to the caller's own
    # company - an unscoped caller still syncs them all.
    "syncGpPos": SIGNED_IN,
    "updateProject": TENANT_OWNERS,
    # --- relay.py -------------------------------------------------------------------------
    # The gp_* reads are signed-in because every PO screen needs them. Three exceptions: two return
    # staff rosters by another name (`gpBuyersDetailed`, buyer ids with names, and `gpEmployees`), and
    # `gpCostCodeMaster` has exactly one consumer, the create-job dialog, so it sits at the bar the
    # `createGpJob` it feeds already sets - all three at TENANT_OWNERS. Everything that provisions,
    # adopts or deletes a relay install is UC NEXUS ADMIN: those are relay credentials, and one
    # install serves every company at once.
    "gpBuyers": SIGNED_IN,
    "gpBuyersDetailed": TENANT_OWNERS,
    "gpCostCodeMaster": TENANT_OWNERS,
    "gpCostCodes": SIGNED_IN,
    "gpCustomerAddresses": SIGNED_IN,
    "gpCustomers": SIGNED_IN,
    "gpDivisions": SIGNED_IN,
    "gpEmployees": TENANT_OWNERS,
    "gpJobs": SIGNED_IN,
    "gpPoEntryOptions": SIGNED_IN,
    "gpPoTotals": SIGNED_IN,
    "gpTaxDetails": SIGNED_IN,
    "gpTaxSchedules": SIGNED_IN,
    "gpVendorAddresses": SIGNED_IN,
    "gpVendors": SIGNED_IN,
    "relayAdoptWindow": NEXUS_ADMIN_ROLE,
    "relayEvents": NEXUS_ADMIN_ROLE,
    "relayInstalls": NEXUS_ADMIN_ROLE,
    "relayStatus": SIGNED_IN,
    "suggestVendorForManufacturer": SIGNED_IN,
    "armRelayAdopt": NEXUS_ADMIN_ROLE,
    # The two GP writes that are sub-steps of a Tenant Owner screen: creating a buyer lives inside
    # the GP identity chooser on the Edit User dialog, and adding a customer address inside the
    # Create GP Job dialog. Each sits at the bar its host page sets.
    "createGpBuyer": TENANT_OWNERS,
    "createGpCustomerAddress": TENANT_OWNERS,
    "deleteRelayInstall": NEXUS_ADMIN_ROLE,
    "disarmRelayAdopt": NEXUS_ADMIN_ROLE,
    "provisionRelayInstall": NEXUS_ADMIN_ROLE,
    # `enrollRelayInstall` is in OPEN_OPERATIONS above, not here.
    # --- sharepoint_migration.py ----------------------------------------------------------
    # UC NEXUS ADMIN on both counts: the query reads another system entirely over the company's
    # Graph credentials, and the mutation writes inventory in bulk with no per-row undo. The
    # migration is a one-off operation on the deployment, not work inside a company.
    "sharepointInventorySnapshot": NEXUS_ADMIN_ROLE,
    "migrateSharepointInventory": NEXUS_ADMIN_ROLE,
    # The same bar for the same reason: it exists to serve the migration wizard's Reconcile GP PO
    # link step, and it reads purchase orders by number in bulk.
    "mirroredPosByNumber": NEXUS_ADMIN_ROLE,
    # SIGNED_IN, unlike its two neighbours: this one only reads a project's own schedule products, the
    # same thing projectHardwareSchedule already publishes to anyone signed in, and the Nexus
    # Registration panel needs it to offer a buyer the products a GP-born PO's lines could be for.
    "projectScheduleProducts": SIGNED_IN,
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
    # The shipping department's own list of how a load travels (#451). The read stays SIGNED_IN -
    # every screen that books a load offers the list - but maintaining it is the SHIPPING MANAGER's
    # (#729), because it is the shape every shipment in the company is recorded against.
    "shipmentMethods": SIGNED_IN,
    "createShipmentMethod": SHIPPING_MANAGERS,
    "updateShipmentMethod": SHIPPING_MANAGERS,
    "deleteShipmentMethod": SHIPPING_MANAGERS,
    "shipReadyItems": SIGNED_IN,
    # Read-only coverage for the shipping-out builder (#451). SIGNED_IN because its caller is the
    # Start-a-Request wizard, which every module's users reach.
    "requestCoverage": SIGNED_IN,
    "shippingOutRequests": SIGNED_IN,
    # One request by id, read by the request workspace's edit mode. SIGNED_IN like its list sibling.
    "shippingOutRequest": SIGNED_IN,
    # Deciding a request - taking it on, turning it down, or putting a decided one back on the
    # board - is the SHIPPING MANAGER's (#729). Raising one and confirming a truck are not: anybody
    # in the company may ask for a load and anybody loading it records what left.
    "acceptShippingOutRequest": SHIPPING_MANAGERS,
    "confirmShipment": SIGNED_IN,
    "createShipmentReturn": SIGNED_IN,
    # Raising and correcting a request from the Shipping module (#451). SIGNED_IN: the same people
    # work this board, and both are gated on request state, not role.
    "createShippingOutRequest": SIGNED_IN,
    "editShippingOutRequest": SIGNED_IN,
    "rejectShippingOutRequest": SHIPPING_MANAGERS,
    "reopenShippingOutRequest": SHIPPING_MANAGERS,
    # The Delivery Request lifecycle (#447), SIGNED_IN for the same reason confirmShipment is: the
    # shipping department, the warehouse and the office all work the same Shipments page, so no one
    # role's module owns the callers. The lifecycle mutations move nothing - they record where the
    # truck got to - and the edit is refused on state rather than on role.
    "updateShipmentDetails": SIGNED_IN,
    "markShipmentPickedUp": SIGNED_IN,
    "markShipmentDelivered": SIGNED_IN,
    # --- shop_assembly.py -----------------------------------------------------------------
    # The reads are SIGNED_IN: they are the same availability and request-state arithmetic every
    # other screen shows, and the PM raising a request has to be able to watch it.
    #
    # The four writes are the Shop Assembly Manager's board (#646). Batching commits real inventory
    # (it reserves stock and puts a pull on the warehouse floor), and dismissing, rejecting and
    # discarding are the same authority used the other way - so all four name the role the issue
    # gives the decision to, with the tenant owners beside it as an any-of rather than an implicit
    # bypass. There is no implicit admin bypass anywhere in this table.
    "shopAssemblyRequests": SIGNED_IN,
    "shopAssemblyRequest": SIGNED_IN,
    "shopAssemblyAllocationReview": SIGNED_IN,
    "createShopAssemblyBatch": SHOP_ASSEMBLY_MANAGERS,
    "dismissShopAssemblyOpenings": SHOP_ASSEMBLY_MANAGERS,
    "rejectShopAssemblyRequest": SHOP_ASSEMBLY_MANAGERS,
    "discardShopAssemblyBatch": SHOP_ASSEMBLY_MANAGERS,
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
    # the roles every other entry in this table is gated on, so an open copy is a self-service
    # escalation into all of them.
    #
    # TENANT_OWNERS since #729, not the cross-tenant role: a TENANT OWNER runs their own company's
    # people. What keeps that from being an escalation is in the body - `users` shows them only
    # their own company's accounts, and the grant rules refuse them a target in another company or
    # a roles change that adds or removes UC Nexus Admin or DB Admin.
    "users": TENANT_OWNERS,
    # `updateUserCompany` is the exception, and it is the one that has to be: it decides which
    # company's rows an account can read and write at all (#637). A TENANT OWNER who could set it
    # would be deciding the boundary they are themselves confined to, so it stays UC NEXUS ADMIN.
    "updateUserCompany": NEXUS_ADMIN_ROLE,
    "updateUserGpBuyerId": TENANT_OWNERS,
    "updateUserName": TENANT_OWNERS,
    "updateUserRoles": TENANT_OWNERS,
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
    # The Location Cleanup page on the Tenant Owner module reads this and acts on it with
    # `mergeLocations`; both are scoped to the caller's own company.
    "locationDuplicates": TENANT_OWNERS,
    "locationUtilization": SIGNED_IN,
    "poReceivingDetails": SIGNED_IN,
    "projectInventoryAvailability": SIGNED_IN,
    # The POs behind a hardwareStatusByProduct figure (#732): the same reach as that rollup.
    "projectProductPoLines": SIGNED_IN,
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
    # The registry read feeds every put-away picker, so it is signed-in; defining and retiring
    # locations is warehouse management.
    "warehouseLocations": SIGNED_IN,
    "createWarehouseLocation": WAREHOUSE_MANAGERS,
    "deactivateWarehouseLocation": WAREHOUSE_MANAGERS,
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
    # A building belongs to a GP company, so raising, editing and retiring one is the tenant
    # owners' - each of the three is checked against the caller's own company in the body.
    "createWarehouse": TENANT_OWNERS,
    "deleteReceiveDraft": SIGNED_IN,
    "deleteWarehouse": TENANT_OWNERS,
    "markInventoryUnlocated": SIGNED_IN,
    "mergeLocations": TENANT_OWNERS,
    "moveInventoryLocation": SIGNED_IN,
    "overrideInventoryQuantity": SIGNED_IN,
    "rejectReceiveDraft": WAREHOUSE_MANAGERS,
    "resubmitReceiveDraft": SIGNED_IN,
    "savePickDraft": SIGNED_IN,
    "startPullRequestPick": SIGNED_IN,
    "updateReceiveDraft": SIGNED_IN,
    "updateWarehouse": TENANT_OWNERS,
}


def _roles_for(context, field_name: str) -> list[str]:
    """The caller's Clerk roles, taken from whichever call this operation was going to make anyway.

    Both paths are memoised on the request context, so a query hitting several role-gated root fields
    resolves roles once, not once per field."""
    if field_name in ROSTER_BACKED:
        user_id = authenticated_user_id(context)
        for u in user_roster(context):
            if u.get("id") == user_id:
                # Memoised as this request's answer, so a body that goes on to call `tenant_scope`
                # (adminStats and users both do since #729) does not send us back to Clerk for the
                # metadata this roster row already carries.
                return remember_roster_entry(context, u)
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
