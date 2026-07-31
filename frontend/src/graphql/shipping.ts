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

// Every field of the Delivery Request a shipment carries (#447), in one place. The confirm, the
// list read and the three lifecycle mutations all return a PackingSlip, and they have to return the
// SAME PackingSlip: Apollo normalises on `id`, so a mutation that answered with a narrower selection
// than the list reads would leave the row it just changed half-stale in the cache.
const PACKING_SLIP_FIELDS = `
  id
  packingSlipNumber
  projectId
  status
  shippedBy
  shippedAt
  createdAt
  pickupDate
  deliveryDate
  shipperEmail
  shipperPhone
  pickupLocation
  carrierTagBol
  weightLbs
  deliveryAddress
  specialInstructions
  gateNumber
  forkliftOnsite
  materialComingBack
  siteMaterialIncluded
  constructionTempKeys
  extraFrameAnchors
  contractorContactName
  contractorContactPhone
  ucshContactName
  ucshContactPhone
  salesOrderNumber
  pickedUpAt
  pickedUpBy
  deliveredAt
  deliveredBy
`;

export const GET_PACKING_SLIPS = gql`
  query GetPackingSlips($projectId: ID) {
    packingSlips(projectId: $projectId) {
      ${PACKING_SLIP_FIELDS}
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
      ${PACKING_SLIP_FIELDS}
      items {
        id
        packingSlipId
        itemType
        openingItemId
        openingNumber
        leaf
        productCode
        hardwareCategory
        quantity
      }
    }
  }
`;

// The Delivery Request is editable only while the shipment is still SCHEDULED - once it has been
// picked up, the paper is out of the building and the record has to match it. The backend enforces
// that; the list hides the button.
export const UPDATE_SHIPMENT_DETAILS = gql`
  mutation UpdateShipmentDetails($input: UpdateShipmentDetailsInput!) {
    updateShipmentDetails(input: $input) {
      ${PACKING_SLIP_FIELDS}
    }
  }
`;

export const MARK_SHIPMENT_PICKED_UP = gql`
  mutation MarkShipmentPickedUp($id: ID!) {
    markShipmentPickedUp(id: $id) {
      ${PACKING_SLIP_FIELDS}
    }
  }
`;

export const MARK_SHIPMENT_DELIVERED = gql`
  mutation MarkShipmentDelivered($id: ID!) {
    markShipmentDelivered(id: $id) {
      ${PACKING_SLIP_FIELDS}
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
      integrityNote
      items {
        id
        itemType
        openingNumber
        openingItemId
        leaf
        hardwareCategory
        productCode
        requestedQuantity
      }
    }
  }
`;

export const ACCEPT_SHIPPING_OUT_REQUEST = gql`
  mutation AcceptShippingOutRequest($id: ID!) {
    acceptShippingOutRequest(id: $id) {
      id
      status
    }
  }
`;

export const REJECT_SHIPPING_OUT_REQUEST = gql`
  mutation RejectShippingOutRequest($id: ID!, $reason: String) {
    rejectShippingOutRequest(id: $id, reason: $reason) {
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
