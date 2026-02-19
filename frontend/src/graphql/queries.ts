import { gql } from '@apollo/client/core';

export const GET_PROJECTS = gql`
  query GetProjects {
    projects {
      id
      projectId
      description
      jobSiteName
    }
  }
`;

export const GET_PO_STATISTICS = gql`
  query GetPOStatistics($projectId: ID!) {
    poStatistics(projectId: $projectId) {
      total
      draft
      ordered
      partiallyReceived
      closed
      cancelled
    }
  }
`;

export const GET_PURCHASE_ORDERS = gql`
  query GetPurchaseOrders($projectId: ID!, $status: POStatus) {
    purchaseOrders(projectId: $projectId, status: $status) {
      id
      poNumber
      projectId
      status
      vendorName
      vendorContact
      expectedDeliveryDate
      orderedAt
      createdAt
      updatedAt
      lineItems {
        id
        poId
        hardwareCategory
        productCode
        classification
        orderedQuantity
        receivedQuantity
        unitCost
        createdAt
        updatedAt
      }
      receiveRecords {
        id
        poId
        receivedAt
        receivedBy
        createdAt
        lineItems {
          id
          receiveRecordId
          poLineItemId
          hardwareCategory
          productCode
          quantityReceived
          createdAt
        }
      }
    }
  }
`;

export const GET_PURCHASE_ORDER = gql`
  query GetPurchaseOrder($id: ID!) {
    purchaseOrder(id: $id) {
      id
      poNumber
      projectId
      status
      vendorName
      vendorContact
      expectedDeliveryDate
      orderedAt
      createdAt
      updatedAt
      lineItems {
        id
        poId
        hardwareCategory
        productCode
        classification
        orderedQuantity
        receivedQuantity
        unitCost
        createdAt
        updatedAt
      }
      receiveRecords {
        id
        poId
        receivedAt
        receivedBy
        createdAt
        lineItems {
          id
          receiveRecordId
          poLineItemId
          hardwareCategory
          productCode
          quantityReceived
          createdAt
        }
      }
    }
  }
`;

export const GET_INVENTORY_HIERARCHY = gql`
  query GetInventoryHierarchy($projectId: ID!) {
    inventoryHierarchy(projectId: $projectId) {
      hardwareCategory
      totalQuantity
      productCodes {
        productCode
        totalQuantity
        items {
          id
          projectId
          poLineItemId
          receiveLineItemId
          hardwareCategory
          productCode
          quantity
          shelf
          column
          row
          receivedAt
          createdAt
          updatedAt
        }
      }
    }
  }
`;

export const GET_INVENTORY_ITEMS = gql`
  query GetInventoryItems($projectId: ID!, $category: String!, $productCode: String!) {
    inventoryItems(projectId: $projectId, category: $category, productCode: $productCode) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId
        hardwareCategory productCode quantity
        shelf column row receivedAt createdAt updatedAt
      }
      poNumber
      classification
    }
  }
`;

export const GET_OPENING_ITEMS = gql`
  query GetOpeningItems($projectId: ID!) {
    openingItems(projectId: $projectId) {
      id projectId openingId openingNumber
      building floor location quantity
      assemblyCompletedAt state
      shelf column row
      createdAt updatedAt
      installedHardware {
        id openingItemId productCode hardwareCategory quantity
      }
    }
  }
`;

export const GET_OPENING_ITEM_DETAILS = gql`
  query GetOpeningItemDetails($id: ID!) {
    openingItemDetails(id: $id) {
      openingItem {
        id projectId openingId openingNumber
        building floor location quantity
        assemblyCompletedAt state
        shelf column row
        createdAt updatedAt
        installedHardware {
          id openingItemId productCode hardwareCategory quantity
        }
      }
      installedHardware {
        id openingItemId productCode hardwareCategory quantity
      }
    }
  }
`;

export const GET_OPEN_POS = gql`
  query GetOpenPOs($projectId: ID!) {
    openPOs(projectId: $projectId) {
      id
      poNumber
      projectId
      status
      vendorName
      orderedAt
      lineItems {
        id
        hardwareCategory
        productCode
        orderedQuantity
        receivedQuantity
      }
    }
  }
`;

export const GET_PO_RECEIVING_DETAILS = gql`
  query GetPOReceivingDetails($poId: ID!) {
    poReceivingDetails(poId: $poId) {
      id
      poNumber
      vendorName
      status
      lineItems {
        id
        poId
        hardwareCategory
        productCode
        classification
        orderedQuantity
        receivedQuantity
        unitCost
      }
      receiveRecords {
        id
        receivedAt
        receivedBy
        lineItems {
          id
          poLineItemId
          quantityReceived
        }
      }
    }
  }
`;
