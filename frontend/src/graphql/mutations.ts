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

export const ADJUST_INVENTORY_QUANTITY = gql`
  mutation AdjustInventoryQuantity($inventoryLocationId: ID!, $adjustment: Int!, $reason: String!) {
    adjustInventoryQuantity(inventoryLocationId: $inventoryLocationId, adjustment: $adjustment, reason: $reason) {
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
`;

export const MOVE_INVENTORY_LOCATION = gql`
  mutation MoveInventoryLocation($inventoryLocationId: ID!, $newShelf: String!, $newColumn: String!, $newRow: String!) {
    moveInventoryLocation(inventoryLocationId: $inventoryLocationId, newShelf: $newShelf, newColumn: $newColumn, newRow: $newRow) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity shelf column row receivedAt createdAt updatedAt
    }
  }
`;

export const MARK_INVENTORY_UNLOCATED = gql`
  mutation MarkInventoryUnlocated($inventoryLocationId: ID!) {
    markInventoryUnlocated(inventoryLocationId: $inventoryLocationId) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity shelf column row receivedAt createdAt updatedAt
    }
  }
`;

export const ASSIGN_INVENTORY_LOCATION = gql`
  mutation AssignInventoryLocation($inventoryLocationId: ID!, $shelf: String!, $column: String!, $row: String!) {
    assignInventoryLocation(inventoryLocationId: $inventoryLocationId, shelf: $shelf, column: $column, row: $row) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity shelf column row receivedAt createdAt updatedAt
    }
  }
`;

export const MOVE_OPENING_ITEM_LOCATION = gql`
  mutation MoveOpeningItemLocation($openingItemId: ID!, $shelf: String!, $column: String!, $row: String!) {
    moveOpeningItemLocation(openingItemId: $openingItemId, shelf: $shelf, column: $column, row: $row) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state shelf column row createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const MARK_OPENING_ITEM_UNLOCATED = gql`
  mutation MarkOpeningItemUnlocated($openingItemId: ID!) {
    markOpeningItemUnlocated(openingItemId: $openingItemId) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state shelf column row createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const ASSIGN_OPENING_ITEM_LOCATION = gql`
  mutation AssignOpeningItemLocation($openingItemId: ID!, $shelf: String!, $column: String!, $row: String!) {
    assignOpeningItemLocation(openingItemId: $openingItemId, shelf: $shelf, column: $column, row: $row) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state shelf column row createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const CREATE_RECEIVE = gql`
  mutation CreateReceive($input: CreateReceiveInput!) {
    createReceive(input: $input) {
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
`;
