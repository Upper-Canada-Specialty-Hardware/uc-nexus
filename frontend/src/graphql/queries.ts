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
  query GetPOStatistics($projectId: ID) {
    poStatistics(projectId: $projectId) {
      total
      draft
      ordered
      vendorConfirmed
      partiallyReceived
      closed
      cancelled
    }
  }
`;

export const GET_PURCHASE_ORDERS = gql`
  query GetPurchaseOrders($projectId: ID, $status: POStatus) {
    purchaseOrders(projectId: $projectId, status: $status) {
      id
      poNumber
      requestNumber
      projectId
      status
      vendorName
      vendorContact
      vendorQuoteNumber
      notes
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
        orderAs
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
      documents {
        id
        poId
        fileName
        contentType
        fileSize
        documentType
        uploadedAt
        downloadUrl
      }
    }
  }
`;

export const GET_INVENTORY_HIERARCHY = gql`
  query GetInventoryHierarchy($projectId: ID) {
    inventoryHierarchy(projectId: $projectId) {
      hardwareCategory
      totalQuantity
      totalValue
      productCodes {
        productCode
        totalQuantity
        totalValue
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
  query GetInventoryItems($projectId: ID, $category: String!, $productCode: String!) {
    inventoryItems(projectId: $projectId, category: $category, productCode: $productCode) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId
        hardwareCategory productCode quantity
        aisle bay bin receivedAt createdAt updatedAt
      }
      poNumber
      classification
      unitCost
    }
  }
`;

export const GET_OPENING_ITEMS = gql`
  query GetOpeningItems($projectId: ID) {
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
  query GetOpenPOs($projectId: ID) {
    openPOs(projectId: $projectId) {
      id
      poNumber
      projectId
      status
      vendorName
      notes
      orderedAt
      expectedDeliveryDate
      lineItems {
        id
        hardwareCategory
        productCode
        orderedQuantity
        receivedQuantity
        orderAs
      }
    }
  }
`;

export const GET_UNLOCATED_INVENTORY = gql`
  query GetUnlocatedInventory($projectId: ID) {
    unlocatedInventory(projectId: $projectId) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId
        hardwareCategory productCode quantity
        aisle bay bin receivedAt createdAt updatedAt
      }
      poNumber
      classification
      unitCost
    }
  }
`;

export const GET_RECENT_RECEIVE_RECORDS = gql`
  query GetRecentReceiveRecords($limit: Int) {
    recentReceiveRecords(limit: $limit) {
      receiveRecord {
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
      poNumber
      totalItemsReceived
    }
  }
`;

export const GET_PO_RECEIVING_DETAILS = gql`
  query GetPOReceivingDetails($poId: ID!) {
    poReceivingDetails(poId: $poId) {
      id
      poNumber
      requestNumber
      vendorName
      notes
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
        orderAs
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
  query GetShopAssemblyRequests($projectId: ID, $status: ShopAssemblyRequestStatus) {
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
  query GetAssembleList($projectId: ID) {
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
  query GetPullRequests($projectId: ID, $source: PullRequestSource, $status: PullRequestStatus) {
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
  query GetShipReadyItems($projectId: ID) {
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

export const GET_PROJECT_EXCLUDED_ITEMS = gql`
  query GetProjectExcludedItems($projectId: ID!) {
    projectExcludedItems(projectId: $projectId) {
      hardwareCategory
      productCode
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
  query GetHardwareSummary($projectId: ID) {
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
  query GetOpeningHardwareStatus($projectId: ID) {
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

export const GET_USERS = gql`
  query GetUsers {
    users {
      id
      firstName
      lastName
      email
      roles
      imageUrl
    }
  }
`;

export const GET_INVENTORY_BY_VENDOR = gql`
  query GetInventoryByVendor($projectId: ID) {
    inventoryByVendor(projectId: $projectId) {
      vendorName
      totalQuantity
      totalValue
      productCodes {
        productCode
        totalQuantity
        totalValue
        items {
          id projectId poLineItemId receiveLineItemId
          hardwareCategory productCode quantity
          aisle bay bin receivedAt createdAt updatedAt
        }
      }
    }
  }
`;

export const GET_LOCATION_UTILIZATION = gql`
  query GetLocationUtilization {
    locationUtilization {
      aisle
      bay
      bin
      itemCount
      totalQuantity
    }
  }
`;

export const GET_LOCATION_CONTENTS = gql`
  query GetLocationContents($aisle: String!, $bay: String, $bin: String) {
    locationContents(aisle: $aisle, bay: $bay, bin: $bin) {
      inventoryItems {
        inventoryLocation {
          id projectId poLineItemId receiveLineItemId
          hardwareCategory productCode quantity
          aisle bay bin receivedAt createdAt updatedAt
        }
        poNumber
        unitCost
      }
      openingItems {
        id projectId openingId openingNumber
        building floor location quantity
        assemblyCompletedAt state aisle bay bin
        createdAt updatedAt
        installedHardware { id openingItemId productCode hardwareCategory quantity }
      }
    }
  }
`;

export const GET_EXPECTED_DELIVERIES = gql`
  query GetExpectedDeliveries($projectId: ID) {
    expectedDeliveries(projectId: $projectId) {
      id
      poNumber
      requestNumber
      vendorName
      expectedDeliveryDate
      orderedAt
      status
      lineItems {
        id
        hardwareCategory
        productCode
        orderedQuantity
        receivedQuantity
        unitCost
      }
    }
  }
`;

export const GET_BACK_ORDERED_ITEMS = gql`
  query GetBackOrderedItems($projectId: ID) {
    backOrderedItems(projectId: $projectId) {
      hardwareCategory
      productCode
      orderedQuantity
      receivedQuantity
      outstandingQuantity
      unitCost
      poNumber
      vendorName
      expectedDeliveryDate
    }
  }
`;

export const GET_WAREHOUSE_DASHBOARD = gql`
  query GetWarehouseDashboard {
    warehouseDashboard {
      totalItemCount
      totalValue
      unlocatedCount
      pendingPullShop
      pendingPullShipping
      receivedLast7Days
      backOrderedCount
    }
  }
`;

export const GET_WAREHOUSE_AISLES = gql`
  query GetWarehouseAisles($activeOnly: Boolean) {
    warehouseAisles(activeOnly: $activeOnly) {
      id name label xPosition yPosition width height isActive
      bays {
        id aisleId name rowPosition colPosition isActive
        bins {
          id bayId name rowPosition colPosition capacity isActive
        }
      }
    }
  }
`;

export const GET_WAREHOUSE_OVERVIEW = gql`
  query GetWarehouseOverview {
    warehouseOverview {
      id name label xPosition yPosition width height isActive
      totalQuantity itemCount totalCapacity
      bays {
        id aisleId name rowPosition colPosition isActive
        bins {
          id bayId name rowPosition colPosition capacity isActive
        }
      }
    }
  }
`;

export const GET_SUGGEST_PUT_AWAY = gql`
  query GetSuggestPutAway($productCode: String!, $hardwareCategory: String!, $quantity: Int) {
    suggestPutAway(productCode: $productCode, hardwareCategory: $hardwareCategory, quantity: $quantity) {
      aisle bay bin reason currentQuantity capacity
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
