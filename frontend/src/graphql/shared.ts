import { gql } from '@apollo/client/core';

export const GET_PROJECTS = gql`
  query GetProjects {
    projects {
      id
      projectId
      description
      client
      jobSiteName
      openingCount
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

export const GET_BUYER_ASSIGNMENTS = gql`
  query GetBuyerAssignments {
    buyerAssignments {
      buyerId
      costCodes
      projects {
        id
        projectId
        description
      }
    }
  }
`;
