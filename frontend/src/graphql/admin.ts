import { gql } from '@apollo/client/core';

// One project row as the admin screens read it. Shared by the grid, the edit mutation and the detail
// page so the three can never drift into normalizing the same Project with different fields.
// #637: company + archived ride along - adminProjects returns every company's jobs, archived included.
const ADMIN_PROJECT_FIELDS = `
  id
  projectId
  description
  client
  jobSiteName
  company
  archived
  address
  city
  state
  zip
  contractor
  projectManager
  application
  gcContactName
  gcPhone
  gcEmail
  offSiteStorageAgreement
  submittalJobNo
  submittalAssignmentCount
  estimatorCode
  titanUserId
  openingCount
  createdAt
  updatedAt
  gpSetupOk
  gpSetupCheckedAt
  gpSetupIssues {
    costCode
    accountIndex
  }
`;

// #637: company is the tenant this account is scoped to. Every user mutation returns it so a save
// cannot leave the grid showing the pre-save company.
const CLERK_USER_FIELDS = `
  id
  firstName
  lastName
  email
  roles
  gpBuyerId
  company
  imageUrl
`;

export const GET_ADMIN_PROJECTS = gql`
  query GetAdminProjects {
    adminProjects {
      ${ADMIN_PROJECT_FIELDS}
    }
  }
`;

// One project's at-a-glance state for the admin detail page (#637). The counts are computed
// server-side - the page must not walk relationships to add them up.
export const GET_ADMIN_PROJECT_DETAIL = gql`
  query GetAdminProjectDetail($id: ID!) {
    adminProjectDetail(id: $id) {
      project {
        ${ADMIN_PROJECT_FIELDS}
      }
      poCountsByStatus {
        status
        count
      }
      inventoryOnHand
      openShippingRequestCount
    }
  }
`;

export const GET_USERS = gql`
  query GetUsers {
    users {
      ${CLERK_USER_FIELDS}
    }
  }
`;

export const RELAY_INSTALLS = gql`
  query RelayInstalls {
    relayInstalls {
      id
      label
      hostname
      enrolled
      enrolledAt
      lastSeenAt
      createdAt
      adoptedAt
      adoptedBy
      secretHash
    }
  }
`;

// The relay-link connection log, newest first. A refused connection leaves no other trace, so this
// is the only place an admin can see that a relay is dialling in and being turned away.
export const RELAY_EVENTS = gql`
  query RelayEvents($limit: Int) {
    relayEvents(limit: $limit) {
      id
      at
      kind
      installId
      installLabel
      build
      companies
      reason
    }
  }
`;

// The admin-armed "adopt next relay connection" window (#353). While one is open, the next relay to
// dial /relay-link is accepted with whatever secret it presents - the only way to recover a relay
// whose in-memory secret has drifted when nobody can reach the workstation.
export const RELAY_ADOPT_WINDOW = gql`
  query RelayAdoptWindow {
    relayAdoptWindow {
      installId
      label
      expiresAt
      armedBy
    }
  }
`;

export const ARM_RELAY_ADOPT = gql`
  mutation ArmRelayAdopt($installId: ID!) {
    armRelayAdopt(installId: $installId) {
      installId
      label
      expiresAt
      armedBy
    }
  }
`;

export const DISARM_RELAY_ADOPT = gql`
  mutation DisarmRelayAdopt {
    disarmRelayAdopt
  }
`;

// Removing an install deletes the row and revokes its secret (#366). Refused by the backend for the
// install currently holding the connection; the UI disables it there rather than letting it fail.
export const DELETE_RELAY_INSTALL = gql`
  mutation DeleteRelayInstall($installId: ID!) {
    deleteRelayInstall(installId: $installId)
  }
`;

export const GET_LOCATION_DUPLICATES = gql`
  query GetLocationDuplicates {
    locationDuplicates {
      warehouseId
      warehouseLabel
      canonicalAisle
      canonicalRow
      canonicalBay
      variants { aisle row bay }
    }
  }
`;

export const GET_PROJECT_PROGRESS_BY_PRODUCT = gql`
  query GetProjectProgressByProduct($projectId: ID!) {
    projectProgressByProduct(projectId: $projectId) {
      hardwareCategory
      productCode
      requiredQuantity
      poDrafted
      orderedQuantity
      receivedQuantity
      backOrdered
      shippedOut
    }
  }
`;

// Hardware Status by Project: one row per (category, product code), quantities summed across the
// selected projects. sentToShop is a lifecycle exit - shop assembly is outside the Nexus pipeline.
export const GET_HARDWARE_STATUS_BY_PRODUCT = gql`
  query GetHardwareStatusByProduct($projectIds: [ID!]!) {
    hardwareStatusByProduct(projectIds: $projectIds) {
      hardwareCategory
      productCode
      requiredQuantity
      notPurchased
      poDrafted
      onOrder
      receivedQuantity
      onHand
      sentToShop
      stagedForShipping
      shippedOut
      returnedToProject
    }
  }
`;

export const GET_ADMIN_STATS = gql`
  query GetAdminStats {
    adminStats {
      userCount
      hardwareItemCount
      openingCount
      dbAccessEnabled
    }
  }
`;

// ---------------------------------------------------------------------------
// Stock pool + deficiency
// ---------------------------------------------------------------------------

export const OVERRIDE_INVENTORY_QUANTITY = gql`
  mutation OverrideInventoryQuantity($input: OverrideInventoryQuantityInput!) {
    overrideInventoryQuantity(input: $input) {
      id
      projectId
      poLineItemId
      receiveLineItemId
      stockItemId
      hardwareCategory
      productCode
      quantity
      deficientQuantity
      available
      aisle
      row
      bay
      receivedAt
      createdAt
      updatedAt
    }
  }
`;

export const UPDATE_PROJECT = gql`
  mutation UpdateProject($id: ID!, $input: UpdateProjectInput!) {
    updateProject(id: $id, input: $input) {
      ${ADMIN_PROJECT_FIELDS}
    }
  }
`;

// #637: archiving hides a finished job from every project picker without deleting anything it owns.
// Only id + archived come back - the normalized cache patches the row the grid and detail page hold.
export const SET_PROJECT_ARCHIVED = gql`
  mutation SetProjectArchived($id: ID!, $archived: Boolean!) {
    setProjectArchived(id: $id, archived: $archived) {
      id
      archived
    }
  }
`;

export const UPDATE_USER_ROLES = gql`
  mutation UpdateUserRoles($userId: String!, $roles: [String!]!) {
    updateUserRoles(userId: $userId, roles: $roles) {
      ${CLERK_USER_FIELDS}
    }
  }
`;

const WAREHOUSE_FIELDS = `
  id
  name
  code
  company
  address
  city
  province
  postalCode
  isPrimary
  isActive
  createdAt
  updatedAt
`;

export const CREATE_WAREHOUSE = gql`
  mutation CreateWarehouse($input: CreateWarehouseInput!) {
    createWarehouse(input: $input) {
      ${WAREHOUSE_FIELDS}
    }
  }
`;

export const UPDATE_WAREHOUSE = gql`
  mutation UpdateWarehouse($id: ID!, $input: UpdateWarehouseInput!) {
    updateWarehouse(id: $id, input: $input) {
      ${WAREHOUSE_FIELDS}
    }
  }
`;

export const DELETE_WAREHOUSE = gql`
  mutation DeleteWarehouse($id: ID!) {
    deleteWarehouse(id: $id)
  }
`;

export const MERGE_LOCATIONS = gql`
  mutation MergeLocations(
    $warehouseId: ID!,
    $fromAisle: String!, $fromRow: String!, $fromBay: String!,
    $toAisle: String!, $toRow: String!, $toBay: String!
  ) {
    mergeLocations(
      warehouseId: $warehouseId,
      fromAisle: $fromAisle, fromRow: $fromRow, fromBay: $fromBay,
      toAisle: $toAisle, toRow: $toRow, toBay: $toBay
    ) {
      inventoryLocations
      stockItems
    }
  }
`;

export const PROVISION_RELAY_INSTALL = gql`
  mutation ProvisionRelayInstall($label: String!) {
    provisionRelayInstall(label: $label) {
      installId
      label
      enrollmentToken
      enrollmentTokenExpiresAt
    }
  }
`;

export const UPDATE_USER_NAME = gql`
  mutation UpdateUserName($userId: String!, $firstName: String!, $lastName: String!) {
    updateUserName(userId: $userId, firstName: $firstName, lastName: $lastName) {
      ${CLERK_USER_FIELDS}
    }
  }
`;

export const UPDATE_USER_GP_BUYER_ID = gql`
  mutation UpdateUserGpBuyerId($userId: String!, $gpBuyerId: String) {
    updateUserGpBuyerId(userId: $userId, gpBuyerId: $gpBuyerId) {
      ${CLERK_USER_FIELDS}
    }
  }
`;

// #637: which tenant this account belongs to. null clears it, which puts the user back behind the
// "no company assigned" notice rather than silently showing them nothing.
export const UPDATE_USER_COMPANY = gql`
  mutation UpdateUserCompany($userId: String!, $company: String) {
    updateUserCompany(userId: $userId, company: $company) {
      ${CLERK_USER_FIELDS}
    }
  }
`;

// Issue #409: GP's own buyer master, read live through the relay, so an admin picks a buyer identity
// instead of typing one - and registers a missing one here rather than opening GP. Admin-gated on the
// backend (the descriptions are a staff roster); gpBuyers, the bare-id read behind the Create PO
// dropdown, is unchanged and still any-user.
export const GET_GP_BUYERS_DETAILED = gql`
  query GetGpBuyersDetailed($company: String!) {
    gpBuyersDetailed(company: $company) {
      buyerId
      description
    }
  }
`;

export const CREATE_GP_BUYER = gql`
  mutation CreateGpBuyer($buyerId: String!, $description: String!) {
    createGpBuyer(buyerId: $buyerId, description: $description) {
      buyerId
      description
    }
  }
`;

// costCodes came out of the schema in #438: per-buyer cost-code designation was removed in #430,
// which left the argument as an ignored no-op only so a tab from the previous deploy still validated.
export const SAVE_BUYER_ASSIGNMENT = gql`
  mutation SaveBuyerAssignment($buyerId: String!, $projectIds: [ID!]!) {
    saveBuyerAssignment(buyerId: $buyerId, projectIds: $projectIds) {
      buyerId
      projects {
        id
        projectId
        description
      }
    }
  }
`;

export const DELETE_BUYER_ASSIGNMENT = gql`
  mutation DeleteBuyerAssignment($buyerId: String!) {
    deleteBuyerAssignment(buyerId: $buyerId)
  }
`;

// GP write queue admin actions (#353 PR E). Both are admin-gated on the backend; retrying an
// `ambiguous` entry is genuinely dangerous (GP may already hold the write), which is why the UI
// puts it behind a ConfirmDialog that says to check GP first.
export const RETRY_GP_OUTBOX_ENTRY = gql`
  mutation RetryGpOutboxEntry($id: ID!) {
    retryGpOutboxEntry(id: $id) {
      id
      status
      attempts
      failureKind
      lastError
      nextAttemptAt
    }
  }
`;

export const CANCEL_GP_OUTBOX_ENTRY = gql`
  mutation CancelGpOutboxEntry($id: ID!) {
    cancelGpOutboxEntry(id: $id) {
      id
      status
      attempts
      failureKind
      lastError
      nextAttemptAt
    }
  }
`;

// Issue #380: run one pass of the GP job sync now instead of waiting out the poll interval. The
// background service already syncs on a timer and on every relay reconnect; this is the "show me now"
// button on the admin Projects page.
export const SYNC_GP_JOBS = gql`
  mutation SyncGpJobs {
    syncGpJobs {
      total
      adopted
    }
  }
`;

// The legacy SharePoint inventory list, read live over Graph for the one-time migration wizard.
// Returns every row un-interpreted; the wizard decides which carry migratable quantity.
export const GET_SHAREPOINT_INVENTORY_SNAPSHOT = gql`
  query GetSharepointInventorySnapshot {
    sharepointInventorySnapshot {
      alreadyMigrated
      items {
        spItemId
        partNumber
        scheduledPartNumber
        partCategory
        inventoryType
        locations
        stockQty
        nonStockQty
        projectInventoryQty
        projectNumber
        projectName
        unitCost
        partDescription
        finish
        rating
        mounting
        heightInches
        widthInches
      }
    }
  }
`;

// Each mapped project's schedule products, for the migration wizard's category snap + classification
// step. Fired once the projects are mapped, with the Nexus project ids the PROJECT rows resolve to.
export const GET_PROJECT_SCHEDULE_PRODUCTS = gql`
  query GetProjectScheduleProducts($projectIds: [ID!]!) {
    projectScheduleProducts(projectIds: $projectIds) {
      projectId
      hardwareCategory
      productCode
      classification
      requiredQuantity
    }
  }
`;

export const MIGRATE_SHAREPOINT_INVENTORY = gql`
  mutation MigrateSharepointInventory($input: MigrateSharepointInventoryInput!) {
    migrateSharepointInventory(input: $input) {
      stockItems
      projectLocations
      totalUnits
      catalogItemsCreated
      catalogItemsSkipped
      catalogAttributesCreated
    }
  }
`;

// ---------------------------------------------------------------------------
// Direct database access (db-admin-postgres-access). DB-Admin gated on the backend, and every field
// refuses when the feature is disabled (no proxy / a preview env). The mint/rotate credential is
// returned once and lives only in that response - the page reads it no-cache so it never sits in Apollo.
// ---------------------------------------------------------------------------

export const POSTGRES_ADMINS = gql`
  query PostgresAdmins {
    postgresAdmins {
      dbRole
      clerkUserId
      displayName
      email
      clerkMissing
      active
      createdAt
      lastRotatedAt
    }
  }
`;

export const POSTGRES_ACCESS_AUDIT = gql`
  query PostgresAccessAudit {
    postgresAccessAudit {
      id
      action
      dbRole
      actorClerkId
      actorName
      targetClerkId
      targetName
      createdAt
    }
  }
`;

export const MINT_POSTGRES_ADMIN = gql`
  mutation MintPostgresAdmin($clerkUserId: String!) {
    mintPostgresAdmin(clerkUserId: $clerkUserId) {
      dbRole
      clerkUserId
      adodbConnectionString
      accessConnectionString
    }
  }
`;

export const ROTATE_POSTGRES_ADMIN = gql`
  mutation RotatePostgresAdmin($dbRole: String!) {
    rotatePostgresAdmin(dbRole: $dbRole) {
      dbRole
      clerkUserId
      adodbConnectionString
      accessConnectionString
    }
  }
`;

export const REVOKE_POSTGRES_ADMIN = gql`
  mutation RevokePostgresAdmin($dbRole: String!) {
    revokePostgresAdmin(dbRole: $dbRole)
  }
`;
