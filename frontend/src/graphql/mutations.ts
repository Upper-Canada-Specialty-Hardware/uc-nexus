import { gql } from '@apollo/client/core';

export const UPDATE_PO = gql`
  mutation UpdatePO($id: ID!, $vendorName: String, $vendorContact: String, $expectedDeliveryDate: Date) {
    updatePo(id: $id, vendorName: $vendorName, vendorContact: $vendorContact, expectedDeliveryDate: $expectedDeliveryDate) {
      id
      poNumber
      status
      vendorName
      vendorContact
      expectedDeliveryDate
      orderedAt
      updatedAt
      lineItems {
        id
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
          quantityReceived
        }
      }
    }
  }
`;

export const MARK_PO_AS_ORDERED = gql`
  mutation MarkPOAsOrdered($id: ID!) {
    markPoAsOrdered(id: $id) {
      id
      poNumber
      status
      orderedAt
      updatedAt
      vendorName
      lineItems {
        id
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
          quantityReceived
        }
      }
    }
  }
`;

export const CANCEL_PO = gql`
  mutation CancelPO($id: ID!) {
    cancelPo(id: $id) {
      id
      poNumber
      status
      updatedAt
      lineItems {
        id
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
          quantityReceived
        }
      }
    }
  }
`;
