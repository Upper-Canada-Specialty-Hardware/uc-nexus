import { gql } from '@apollo/client/core';
import { DELIVERY_REQUEST_FIELDS } from '../types/deliveryRequestFields';

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

// The staging workspace (#451): what is staged, and which container it has been put in. One query
// for both halves so they can never disagree about whether a leaf has been loaded.
const CONTAINER_FIELDS = `
  id projectId containerType name packingSlipId createdBy createdAt updatedAt
  items {
    id shipmentContainerId itemType openingItemId openingNumber leaf
    hardwareCategory productCode quantity position
  }
`;

export const GET_STAGING_POOL = gql`
  query GetStagingPool($projectId: ID!) {
    stagingPool(projectId: $projectId) {
      leaves { openingItemId openingNumber leaf building floor location placedInContainerId }
      looseItems { openingNumber hardwareCategory productCode stagedQuantity placedQuantity unplacedQuantity }
      containers { ${CONTAINER_FIELDS} }
    }
  }
`;

export const CREATE_SHIPMENT_CONTAINER = gql`
  mutation CreateShipmentContainer($projectId: ID!, $containerType: ShipmentContainerType!, $name: String!) {
    createShipmentContainer(projectId: $projectId, containerType: $containerType, name: $name) {
      ${CONTAINER_FIELDS}
    }
  }
`;

export const RENAME_SHIPMENT_CONTAINER = gql`
  mutation RenameShipmentContainer($id: ID!, $name: String!) {
    renameShipmentContainer(id: $id, name: $name) { ${CONTAINER_FIELDS} }
  }
`;

export const DELETE_SHIPMENT_CONTAINER = gql`
  mutation DeleteShipmentContainer($id: ID!) {
    deleteShipmentContainer(id: $id)
  }
`;

// Full replace over one container's contents; the list order IS the stacking order.
export const SET_CONTAINER_ITEMS = gql`
  mutation SetContainerItems($input: SetContainerItemsInput!) {
    setContainerItems(input: $input) { ${CONTAINER_FIELDS} }
  }
`;

// The shipping department's list of how a load can travel (#451). `activeOnly` is what the Delivery
// Request form passes; the management screen leaves it off so a retired method stays visible.
const SHIPMENT_METHOD_FIELDS = 'id name isActive sortOrder createdAt updatedAt';

export const GET_SHIPMENT_METHODS = gql`
  query GetShipmentMethods($activeOnly: Boolean) {
    shipmentMethods(activeOnly: $activeOnly) { ${SHIPMENT_METHOD_FIELDS} }
  }
`;

export const CREATE_SHIPMENT_METHOD = gql`
  mutation CreateShipmentMethod($name: String!, $sortOrder: Int) {
    createShipmentMethod(name: $name, sortOrder: $sortOrder) { ${SHIPMENT_METHOD_FIELDS} }
  }
`;

export const UPDATE_SHIPMENT_METHOD = gql`
  mutation UpdateShipmentMethod($id: ID!, $name: String, $isActive: Boolean, $sortOrder: Int) {
    updateShipmentMethod(id: $id, name: $name, isActive: $isActive, sortOrder: $sortOrder) {
      ${SHIPMENT_METHOD_FIELDS}
    }
  }
`;

export const DELETE_SHIPMENT_METHOD = gql`
  mutation DeleteShipmentMethod($id: ID!) {
    deleteShipmentMethod(id: $id)
  }
`;

// Composing a request from the Shipping module rather than from Start a Task (#451). Both answer
// with the whole request, so the pending list updates through the Apollo cache.
const SHIPPING_OUT_REQUEST_FIELDS = `
  id
  requestNumber
  projectId
  status
  createdBy
  createdAt
  integrityNote
  items { id itemType openingNumber openingItemId leaf hardwareCategory productCode requestedQuantity }
`;

export const CREATE_SHIPPING_OUT_REQUEST = gql`
  mutation CreateShippingOutRequest($input: CreateShippingOutRequestInput!) {
    createShippingOutRequest(input: $input) {
      ${SHIPPING_OUT_REQUEST_FIELDS}
    }
  }
`;

// Full replace over the item list: the request ends up with exactly what is sent.
export const EDIT_SHIPPING_OUT_REQUEST = gql`
  mutation EditShippingOutRequest($input: EditShippingOutRequestInput!) {
    editShippingOutRequest(input: $input) {
      ${SHIPPING_OUT_REQUEST_FIELDS}
    }
  }
`;

// What the openings picked in Start a Task still owe the site, leaf by leaf (#451). Joins three
// things the builder cannot see on its own: the schedule (owed), the assembled leaf (installed) and
// the open purchase orders (on order). Availability is deliberately NOT here - it comes from
// projectInventoryAvailability, the single number the creation gate is applied against (#342).
export const GET_SHIPPING_COVERAGE = gql`
  query GetShippingCoverage($projectId: ID!, $openingNumbers: [String!]!) {
    shippingCoverage(projectId: $projectId, openingNumbers: $openingNumbers) {
      openingNumber
      leaf
      status
      openingItemId
      claimedByRequestNumber
      lines {
        hardwareCategory
        productCode
        classification
        owedQuantity
        installedQuantity
        spokenForQuantity
        suggestedQuantity
        onOrderQuantity
      }
    }
  }
`;

// What shipped, and the journey it went on. The Delivery Request header sits between them, and is
// spliced in from DELIVERY_REQUEST_FIELDS rather than listed again (#453): a header field missing
// from this selection saves fine, reads back undefined and prints blank on the form, which is a
// failure no build or test catches.
const SLIP_IDENTITY_FIELDS = [
  'id',
  'packingSlipNumber',
  'projectId',
  'status',
  'shippedBy',
  'shippedAt',
  'createdAt',
] as const;

const SLIP_LIFECYCLE_FIELDS = ['pickedUpAt', 'pickedUpBy', 'deliveredAt', 'deliveredBy'] as const;

// Every field of the Delivery Request a shipment carries (#447), in one place. The confirm, the
// list read and the three lifecycle mutations all return a PackingSlip, and they have to return the
// SAME PackingSlip: Apollo normalises on `id`, so a mutation that answered with a narrower selection
// than the list reads would leave the row it just changed half-stale in the cache.
// How the load was physically arranged (#451), spliced in for the same reason the header is: a
// document that read a slip without its containers would print a Delivery Request that silently
// lost the stacking order, and nothing would fail. Items come back in load order from the server.
const SLIP_CONTAINER_FIELDS = `
  containers {
    id
    containerType
    name
    items {
      id
      itemType
      openingNumber
      leaf
      hardwareCategory
      productCode
      quantity
      position
    }
  }`;

const PACKING_SLIP_FIELDS =
  [...SLIP_IDENTITY_FIELDS, ...DELIVERY_REQUEST_FIELDS, ...SLIP_LIFECYCLE_FIELDS].join('\n  ') +
  SLIP_CONTAINER_FIELDS;

export const GET_PACKING_SLIPS = gql`
  query GetPackingSlips($projectId: ID) {
    packingSlips(projectId: $projectId) {
      ${PACKING_SLIP_FIELDS}
      items {
        id
        itemType
        openingNumber
        leaf
        building
        floor
        location
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
        building
        floor
        location
        productCode
        hardwareCategory
        quantity
      }
    }
  }
`;

// The container flow's confirm (#451): the same slip, composed from whole containers instead of a
// hand-built item list.
export const CONFIRM_SHIPMENT_FROM_CONTAINERS = gql`
  mutation ConfirmShipmentFromContainers($input: ConfirmShipmentFromContainersInput!) {
    confirmShipmentFromContainers(input: $input) {
      ${PACKING_SLIP_FIELDS}
      items {
        id
        packingSlipId
        itemType
        openingItemId
        openingNumber
        leaf
        building
        floor
        location
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
