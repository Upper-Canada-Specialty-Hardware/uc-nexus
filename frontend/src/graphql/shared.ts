import { gql } from '@apollo/client/core';

// gpSetupOk / gpSetupIssues (#425) ride along on every project read: they are scalar columns on the
// project row (no relationship walk, no N+1), and every module that lets a user pick a project has to
// be able to badge a quarantined one rather than discovering it at the submit button.
export const GET_PROJECTS = gql`
  query GetProjects {
    projects {
      id
      projectId
      description
      client
      jobSiteName
      openingCount
      gpSetupOk
      gpSetupCheckedAt
      gpSetupIssues {
        costCode
        accountIndex
      }
    }
  }
`;

export const GET_PRIOR_ORDER_AS_VALUES = gql`
  query GetPriorOrderAsValues($vendorId: ID!, $productCodes: [String!]!) {
    priorOrderAsValues(vendorId: $vendorId, productCodes: $productCodes) {
      productCode
      values
    }
  }
`;

export const GET_NOTIFICATIONS = gql`
  query GetNotifications($projectId: ID, $recipientRole: String, $unreadOnly: Boolean, $limit: Int) {
    notifications(projectId: $projectId, recipientRole: $recipientRole, unreadOnly: $unreadOnly, limit: $limit) {
      id
      projectId
      recipientRole
      type
      message
      isRead
      createdAt
    }
  }
`;

export const GET_VENDORS = gql`
  query GetVendors {
    vendors {
      id
      name
      contactName
      email
      phone
      notes
      createdAt
      updatedAt
    }
  }
`;

export const GET_RELAY_STATUS = gql`
  query GetRelayStatus {
    relayStatus {
      connected
      company
      build
      installId
    }
  }
`;

// The GP write queue (#353 PR E). The summary is polled by the queue chip; the list is read by the
// admin queue table and by the PO lists, which join entries onto rows client-side on `entityKey`.
export const GET_GP_OUTBOX_SUMMARY = gql`
  query GetGpOutboxSummary {
    gpOutboxSummary {
      pending
      inFlight
      failed
      oldestPendingAt
      lastDrainedAt
    }
  }
`;

export const GET_GP_OUTBOX = gql`
  query GetGpOutbox($status: GpOutboxStatus, $limit: Int) {
    gpOutbox(status: $status, limit: $limit) {
      id
      label
      op
      company
      status
      attempts
      nextAttemptAt
      lastError
      failureKind
      entityKey
      createdAt
    }
  }
`;

export const GET_WAREHOUSES = gql`
  query GetWarehouses($includeInactive: Boolean) {
    warehouses(includeInactive: $includeInactive) {
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
    }
  }
`;

export const GET_AUDIT_LOG = gql`
  query GetAuditLog($entityId: ID, $entityType: AuditEntityType, $projectId: ID, $limit: Int) {
    auditLog(entityId: $entityId, entityType: $entityType, projectId: $projectId, limit: $limit) {
      id
      projectId
      entityType
      entityId
      action
      detail
      performedBy
      createdAt
    }
  }
`;

export const MOVE_INVENTORY_LOCATION = gql`
  mutation MoveInventoryLocation($inventoryLocationId: ID!, $newAisle: String!, $newRow: String!, $newBay: String!) {
    moveInventoryLocation(inventoryLocationId: $inventoryLocationId, newAisle: $newAisle, newRow: $newRow, newBay: $newBay) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

export const MARK_INVENTORY_UNLOCATED = gql`
  mutation MarkInventoryUnlocated($inventoryLocationId: ID!) {
    markInventoryUnlocated(inventoryLocationId: $inventoryLocationId) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

export const ASSIGN_INVENTORY_LOCATION = gql`
  mutation AssignInventoryLocation($inventoryLocationId: ID!, $aisle: String!, $row: String!, $bay: String!) {
    assignInventoryLocation(inventoryLocationId: $inventoryLocationId, aisle: $aisle, row: $row, bay: $bay) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

export const MOVE_OPENING_ITEM_LOCATION = gql`
  mutation MoveOpeningItemLocation($openingItemId: ID!, $aisle: String!, $row: String!, $bay: String!, $warehouseId: ID) {
    moveOpeningItemLocation(openingItemId: $openingItemId, aisle: $aisle, row: $row, bay: $bay, warehouseId: $warehouseId) {
      id projectId openingId warehouseId openingNumber building floor location quantity assemblyCompletedAt state aisle row bay createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const MARK_OPENING_ITEM_UNLOCATED = gql`
  mutation MarkOpeningItemUnlocated($openingItemId: ID!) {
    markOpeningItemUnlocated(openingItemId: $openingItemId) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state aisle row bay createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const MARK_NOTIFICATION_AS_READ = gql`
  mutation MarkNotificationAsRead($id: ID!) {
    markNotificationAsRead(id: $id) {
      id
      isRead
    }
  }
`;

// Per-opening door-leaf rollup (#313). No projectId -> all projects (global shop-assembly view);
// rows carry project identity so colliding opening numbers stay distinct.
export const GET_OPENING_LEAF_STATUS = gql`
  query GetOpeningLeafStatus($projectId: ID) {
    openingLeafStatus(projectId: $projectId) {
      projectId
      projectName
      openingNumber
      leafCount
      leaves {
        leaf
        status
      }
    }
  }
`;

// The caller's OWN buyer assignment, for the register-PO dialog's project filter (#216). Scoped
// server-side as of #428, so this returns at most one row - the one matching the caller's linked GP
// buyer id - or none if no id is linked yet. The whole table is `allBuyerAssignments`, admin only.
export const GET_BUYER_ASSIGNMENTS = gql`
  query GetBuyerAssignments {
    buyerAssignments {
      buyerId
      projects {
        id
        projectId
        description
      }
    }
  }
`;

// Every buyer's assignment, for the Buyers admin page. Admin-gated (#428).
export const GET_ALL_BUYER_ASSIGNMENTS = gql`
  query GetAllBuyerAssignments {
    allBuyerAssignments {
      buyerId
      projects {
        id
        projectId
        description
      }
    }
  }
`;
