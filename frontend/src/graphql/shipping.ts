import { gql } from '@apollo/client/core';

export const GET_SHIP_READY_ITEMS = gql`
  query GetShipReadyItems($projectId: ID) {
    shipReadyItems(projectId: $projectId) {
      openingItems {
        id projectId openingId openingNumber building floor location leaf quantity
        assemblyCompletedAt state aisle row bay createdAt updatedAt
        installedHardware { id openingItemId productCode hardwareCategory quantity }
      }
      looseItems {
        openingNumber hardwareCategory productCode availableQuantity
      }
    }
  }
`;

export const GET_PACKING_SLIPS = gql`
  query GetPackingSlips($projectId: ID) {
    packingSlips(projectId: $projectId) {
      id
      packingSlipNumber
      projectId
      shippedBy
      shippedAt
      createdAt
      items {
        id
        itemType
        openingNumber
        leaf
        productCode
        hardwareCategory
        quantity
      }
    }
  }
`;

export const GET_RETURNABLE_LINES = gql`
  query GetReturnableLines($packingSlipId: ID!) {
    returnableLines(packingSlipId: $packingSlipId) {
      packingSlipItemId
      openingNumber
      productCode
      hardwareCategory
      shippedQuantity
      returnedQuantity
      returnableQuantity
    }
  }
`;

export const CONFIRM_SHIPMENT = gql`
  mutation ConfirmShipment($input: ConfirmShipmentInput!) {
    confirmShipment(input: $input) {
      id
      packingSlipNumber
      projectId
      shippedBy
      shippedAt
      createdAt
      items {
        id
        packingSlipId
        itemType
        openingItemId
        openingNumber
        productCode
        hardwareCategory
        quantity
      }
    }
  }
`;

export const GET_SHIPPING_OUT_REQUESTS = gql`
  query GetShippingOutRequests($projectId: ID, $status: ShippingOutRequestStatus, $reopenableOnly: Boolean) {
    shippingOutRequests(projectId: $projectId, status: $status, reopenableOnly: $reopenableOnly) {
      id
      requestNumber
      projectId
      status
      createdBy
      createdAt
      items {
        id
        itemType
        openingNumber
        hardwareCategory
        productCode
        requestedQuantity
      }
    }
  }
`;

export const ACCEPT_SHIPPING_OUT_REQUEST = gql`
  mutation AcceptShippingOutRequest($id: ID!, $acceptedBy: String!) {
    acceptShippingOutRequest(id: $id, acceptedBy: $acceptedBy) {
      id
      status
    }
  }
`;

export const REJECT_SHIPPING_OUT_REQUEST = gql`
  mutation RejectShippingOutRequest($id: ID!, $rejectedBy: String!, $reason: String) {
    rejectShippingOutRequest(id: $id, rejectedBy: $rejectedBy, reason: $reason) {
      id
      status
    }
  }
`;

export const REOPEN_SHIPPING_OUT_REQUEST = gql`
  mutation ReopenShippingOutRequest($id: ID!) {
    reopenShippingOutRequest(id: $id) {
      id
      status
    }
  }
`;

export const CREATE_SHIPMENT_RETURN = gql`
  mutation CreateShipmentReturn($input: CreateShipmentReturnInput!) {
    createShipmentReturn(input: $input) {
      id
      packingSlipId
      warehouseId
      returnedBy
      returnedAt
      reference
      items {
        id
        packingSlipItemId
        disposition
        quantity
        productCode
        hardwareCategory
        openingNumber
        rmaReference
        resultingInventoryLocationId
        resultingStockItemId
      }
    }
  }
`;
