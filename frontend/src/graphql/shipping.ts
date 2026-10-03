import { gql } from '@apollo/client/core';
import { DELIVERY_REQUEST_FIELDS } from '../types/deliveryRequestFields';

// The Shipping landing's pipeline gauges (#589): one rollup for the whole home page.
export const GET_SHIPPING_STATS = gql`
  query GetShippingStats {
    shippingStats {
      pendingRequestCount
      stagingContainerCount
      scheduledShipmentCount
      inTransitShipmentCount
    }
  }
`;

// The staging workspace (#451): what is staged, and which container it has been put in. One query
// for both halves so they can never disagree about whether something has been loaded.
const CONTAINER_FIELDS = `
  id projectId containerType name packingSlipId createdBy createdAt updatedAt
  items {
    id shipmentContainerId openingNumber hardwareCategory productCode quantity isManual position
  }
`;

export const GET_STAGING_POOL = gql`
  query GetStagingPool($projectId: ID!) {
    stagingPool(projectId: $projectId) {
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

// A move from one container to another as one save (#1178): both rewrites commit together, so a
// refused target never leaves the item in neither.
export const MOVE_CONTAINER_ITEMS = gql`
  mutation MoveContainerItems($input: MoveContainerItemsInput!) {
    moveContainerItems(input: $input) { ${CONTAINER_FIELDS} }
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

// Composing a request from the Shipping module rather than from Start a Request (#451). Both answer
// with the whole request, so the pending list updates through the Apollo cache.
const SHIPPING_OUT_REQUEST_FIELDS = `
  id
  requestNumber
  projectId
  status
  createdBy
  createdAt
  integrityNote
  linesVersion
  items { id openingNumber hardwareCategory productCode requestedQuantity }
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

// One request by id, for seeding the request workspace's edit mode. The workspace is its own
// full-page route (/shipping/requests/:id/edit), so it reads the request it is editing directly
// rather than relying on the accept-queue list having been mounted first - a cold deep-link or a
// refresh has no such list in the cache. Null when the id matches nothing (already deleted).
// `project` is the request's own job, archived included (#1257), and `reservedByProduct` is what the
// request really holds on stock, which edit mode adds back as headroom (#1262). Both are resolved only
// by this single-request read.
export const GET_SHIPPING_OUT_REQUEST = gql`
  query GetShippingOutRequest($id: ID!) {
    shippingOutRequest(id: $id) {
      ${SHIPPING_OUT_REQUEST_FIELDS}
      project {
        id
        projectId
        description
        client
        jobSiteName
        scheduleFilename
        company
        openingCount
        gpSetupOk
        gpSetupCheckedAt
        gpSetupIssues {
          costCode
          accountIndex
        }
        gpJobState
      }
      reservedByProduct { hardwareCategory productCode quantity }
    }
  }
`;

// The project's openings, for the request workspace's from-schedule opening picker (#608 review).
// Its own thin resolver, not a slice of projectHardwareSchedule: that query materializes every
// HardwareItem row server-side to answer a three-field selection. This returns the opening fields the
// picker filters/displays on plus the two counts the source card shows.
export const GET_PROJECT_OPENINGS = gql`
  query GetProjectOpenings($projectId: ID!) {
    projectOpenings(projectId: $projectId) {
      openingCount
      hardwareItemCount
      openings {
        openingNumber
        building
        floor
        location
        hand
        doorType
        frameType
        interiorExterior
        keying
        leafCount
      }
    }
  }
`;

// What the selected openings still have coming: `max(owed - sent - claimed, 0)` per product. The
// one answer both composers read - shop assembly and shipping out ask the same question. Availability
// is deliberately NOT here; it comes from projectInventoryAvailability, the single number the
// creation gate is applied against (#342).
export const GET_REQUEST_COVERAGE = gql`
  query GetRequestCoverage($projectId: ID!, $openingNumbers: [String!]!) {
    requestCoverage(projectId: $projectId, openingNumbers: $openingNumbers) {
      openingNumber
      hardwareCategory
      productCode
      classification
      owedQuantity
      sentQuantity
      # #632: the sent total split by exit (through shop vs shipped out).
      assembledQuantity
      shippedQuantity
      claimedQuantity
      suggestedQuantity
      onOrderQuantity
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
  'projectNumber',
  'projectDescription',
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
      openingNumber
      hardwareCategory
      productCode
      quantity
      isManual
      position
    }
  }`;

const PACKING_SLIP_FIELDS =
  [...SLIP_IDENTITY_FIELDS, ...DELIVERY_REQUEST_FIELDS, ...SLIP_LIFECYCLE_FIELDS].join('\n  ') +
  SLIP_CONTAINER_FIELDS;

// One page of the Shipments list (#1107): paged and searched on the server, with the count of
// everything the filter matches so the list can say how many more there are.
export const GET_PACKING_SLIPS = gql`
  query GetPackingSlips($projectId: ID, $search: String, $status: ShipmentStatus, $limit: Int) {
    packingSlips(projectId: $projectId, search: $search, status: $status, limit: $limit) {
      ${PACKING_SLIP_FIELDS}
      items {
        id
        openingNumber
        building
        floor
        location
        productCode
        hardwareCategory
        quantity
        isManual
        returnedQuantity
      }
    }
    packingSlipCount(projectId: $projectId, search: $search, status: $status)
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

// The container flow's confirm (#451): the same slip, composed from whole containers instead of a
// hand-built item list.
export const CONFIRM_SHIPMENT_FROM_CONTAINERS = gql`
  mutation ConfirmShipmentFromContainers($input: ConfirmShipmentFromContainersInput!) {
    confirmShipmentFromContainers(input: $input) {
      ${PACKING_SLIP_FIELDS}
      items {
        id
        packingSlipId
        openingNumber
        building
        floor
        location
        productCode
        hardwareCategory
        quantity
        isManual
        returnedQuantity
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

// Calls off a scheduled shipment nothing can be returned from - one of only manual lines (#1176).
export const CANCEL_SHIPMENT = gql`
  mutation CancelShipment($id: ID!) {
    cancelShipment(id: $id) {
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
  query GetShippingOutRequests($projectId: ID, $status: ShippingOutRequestStatus) {
    shippingOutRequests(projectId: $projectId, status: $status) {
      id
      requestNumber
      projectId
      status
      stage
      createdBy
      createdAt
      approvedBy
      approvedAt
      rejectedBy
      rejectedAt
      rejectionReason
      integrityNote
      returnNote
      pullRequestId
      items {
        id
        openingNumber
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
