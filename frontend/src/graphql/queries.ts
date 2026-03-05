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
        vendorAlias
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
          aisle
          bay
          bin
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
        aisle bay bin receivedAt createdAt updatedAt
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
      aisle bay bin
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
        aisle bay bin
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
        vendorAlias
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
        vendorAlias
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

export const GET_SHOP_ASSEMBLY_REQUESTS = gql`
  query GetShopAssemblyRequests($projectId: ID!, $status: ShopAssemblyRequestStatus) {
    shopAssemblyRequests(projectId: $projectId, status: $status) {
      id
      requestNumber
      projectId
      status
      createdBy
      approvedBy
      rejectedBy
      rejectionReason
      createdAt
      approvedAt
      rejectedAt
      openings {
        id
        shopAssemblyRequestId
        openingId
        pullStatus
        assignedTo
        assemblyStatus
        completedAt
        items {
          id
          shopAssemblyOpeningId
          hardwareCategory
          productCode
          quantity
        }
      }
    }
  }
`;

export const GET_ASSEMBLE_LIST = gql`
  query GetAssembleList($projectId: ID!) {
    assembleList(projectId: $projectId) {
      id
      shopAssemblyRequestId
      openingId
      pullStatus
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
      }
    }
  }
`;

export const GET_PULL_REQUESTS = gql`
  query GetPullRequests($projectId: ID!, $source: PullRequestSource, $status: PullRequestStatus) {
    pullRequests(projectId: $projectId, source: $source, status: $status) {
      id
      requestNumber
      projectId
      source
      status
      requestedBy
      assignedTo
      createdAt
      updatedAt
      approvedAt
      completedAt
      cancelledAt
      items {
        id
        pullRequestId
        itemType
        openingNumber
        openingItemId
        hardwareCategory
        productCode
        requestedQuantity
      }
    }
  }
`;

export const GET_MY_WORK = gql`
  query GetMyWork($assignedTo: String!) {
    myWork(assignedTo: $assignedTo) {
      id
      shopAssemblyRequestId
      openingId
      pullStatus
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
      }
    }
  }
`;

export const GET_SHIP_READY_ITEMS = gql`
  query GetShipReadyItems($projectId: ID!) {
    shipReadyItems(projectId: $projectId) {
      openingItems {
        id projectId openingId openingNumber building floor location quantity
        assemblyCompletedAt state aisle bay bin createdAt updatedAt
        installedHardware { id openingItemId productCode hardwareCategory quantity }
      }
      looseItems {
        openingNumber hardwareCategory productCode availableQuantity
      }
    }
  }
`;

export const GET_PROJECT_BY_SCHEDULE_ID = gql`
  query GetProjectByScheduleId($projectId: String!) {
    projectByScheduleId(projectId: $projectId) {
      id
      projectId
      description
      jobSiteName
    }
  }
`;

export const RECONCILE_SCHEDULE = gql`
  query ReconcileSchedule($projectId: ID!, $items: [ReconciliationItemInput!]!) {
    reconcileSchedule(projectId: $projectId, items: $items) {
      openingNumber
      hardwareCategory
      productCode
      quantity
      status
    }
  }
`;

export const GET_HARDWARE_SUMMARY = gql`
  query GetHardwareSummary($projectId: ID!) {
    hardwareSummary(projectId: $projectId) {
      hardwareCategory
      productCode
      poDrafted
      ordered
      received
      backOrdered
      shippedOut
    }
  }
`;

export const GET_OPENING_HARDWARE_STATUS = gql`
  query GetOpeningHardwareStatus($projectId: ID!) {
    openingHardwareStatus(projectId: $projectId) {
      openingNumber
      building
      floor
      location
      items {
        hardwareCategory
        productCode
        itemQuantity
        status
      }
    }
  }
`;

export const GET_NOTIFICATIONS = gql`
  query GetNotifications($projectId: ID!, $recipientRole: String!, $unreadOnly: Boolean, $limit: Int) {
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
