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
