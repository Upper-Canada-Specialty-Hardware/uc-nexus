import { gql } from '@apollo/client/core';

export const GET_ADMIN_PROJECTS = gql`
  query GetAdminProjects {
    adminProjects {
      id
      projectId
      description
      client
      jobSiteName
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
    }
  }
`;

export const GET_USERS = gql`
  query GetUsers {
    users {
      id
      firstName
      lastName
      email
      roles
      gpBuyerId
      imageUrl
    }
  }
`;

export const RELAY_INSTALLS = gql`
  query RelayInstalls {
    relayInstalls {
      id
      label
      company
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
    }
  }
`;

export const GET_ADMIN_STATS = gql`
  query GetAdminStats {
    adminStats {
      userCount
      hardwareItemCount
      openingCount
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
      id
      projectId
      description
      client
      jobSiteName
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
    }
  }
`;

export const UPDATE_USER_ROLES = gql`
  mutation UpdateUserRoles($userId: String!, $roles: [String!]!) {
    updateUserRoles(userId: $userId, roles: $roles) {
      id
      firstName
      lastName
      email
      roles
      gpBuyerId
      imageUrl
    }
  }
`;

const WAREHOUSE_FIELDS = `
  id
  name
  code
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
  mutation ProvisionRelayInstall($label: String!, $company: String!) {
    provisionRelayInstall(label: $label, company: $company) {
      installId
      label
      company
      enrollmentToken
      enrollmentTokenExpiresAt
    }
  }
`;

export const UPDATE_USER_NAME = gql`
  mutation UpdateUserName($userId: String!, $firstName: String!, $lastName: String!) {
    updateUserName(userId: $userId, firstName: $firstName, lastName: $lastName) {
      id
      firstName
      lastName
      email
      roles
      gpBuyerId
      imageUrl
    }
  }
`;

export const UPDATE_USER_GP_BUYER_ID = gql`
  mutation UpdateUserGpBuyerId($userId: String!, $gpBuyerId: String) {
    updateUserGpBuyerId(userId: $userId, gpBuyerId: $gpBuyerId) {
      id
      firstName
      lastName
      email
      roles
      gpBuyerId
      imageUrl
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
      alreadyHasInventory
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
