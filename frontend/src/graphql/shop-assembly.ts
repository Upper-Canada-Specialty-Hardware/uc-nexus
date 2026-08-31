import { gql } from '@apollo/client/core';

export const GET_SHOP_ASSEMBLY_STATS = gql`
  query GetShopAssemblyStats {
    shopAssemblyStats {
      activePullRequestCount
    }
  }
`;

// Everything the requests page draws per row. A request is raised as a flag over openings and worked
// in batches, so the row carries three collections: the owed lines, each opening's own state, and
// the batches dispatched off it. `stage` and every `pullStatus` are derived server-side in one query
// for the page, never per row.
const REQUEST_FIELDS = `
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
  items {
    id
    openingNumber
    hardwareCategory
    productCode
    requestedQuantity
  }
  openings {
    id
    openingNumber
    status
    batchId
    dismissedBy
    dismissedAt
    dismissalReason
  }
  batches {
    id
    sequence
    batchNumber
    status
    createdBy
    createdAt
    pullRequestId
    pullStatus
    items {
      id
      openingNumber
      hardwareCategory
      productCode
      allocatedQuantity
    }
  }`;

export const GET_SHOP_ASSEMBLY_REQUESTS = gql`
  query GetShopAssemblyRequests($projectId: ID, $status: ShopAssemblyRequestStatus, $reopenableOnly: Boolean) {
    shopAssemblyRequests(projectId: $projectId, status: $status, reopenableOnly: $reopenableOnly) {
      ${REQUEST_FIELDS}
    }
  }
`;

// The landing gauge, which needs a COUNT and a rung and nothing else. Its own document rather than a
// cache-first read of the query above: that one carries every request's lines, openings and batches,
// and materializing all of it to render one number is the "don't request fields you don't use" trap
// the perf rules name.
export const GET_SHOP_ASSEMBLY_REQUEST_STAGES = gql`
  query GetShopAssemblyRequestStages($status: ShopAssemblyRequestStatus) {
    shopAssemblyRequests(status: $status) {
      id
      stage
    }
  }
`;

// What the manager composes a batch against: the request's still-pending openings, each opening's
// owed lines, and the reservation-aware free stock behind them. `availableQuantity` is the
// PROJECT-WIDE pool per product, not a per-opening share - two openings wanting the same hinge are
// competing for it, and the screen spends it down as the manager walks.
export const GET_SHOP_ASSEMBLY_ALLOCATION_REVIEW = gql`
  query GetShopAssemblyAllocationReview($requestId: ID!) {
    shopAssemblyAllocationReview(requestId: $requestId) {
      requestId
      requestNumber
      projectId
      status
      createdBy
      createdAt
      integrityNote
      openings {
        openingNumber
        lines {
          openingNumber
          hardwareCategory
          productCode
          requestedQuantity
          availableQuantity
        }
      }
    }
  }
`;

export const CREATE_SHOP_ASSEMBLY_BATCH = gql`
  mutation CreateShopAssemblyBatch($input: CreateShopAssemblyBatchInput!) {
    createShopAssemblyBatch(input: $input) {
      ${REQUEST_FIELDS}
    }
  }
`;

export const DISMISS_SHOP_ASSEMBLY_OPENINGS = gql`
  mutation DismissShopAssemblyOpenings($requestId: ID!, $openingNumbers: [String!], $reason: String) {
    dismissShopAssemblyOpenings(requestId: $requestId, openingNumbers: $openingNumbers, reason: $reason) {
      ${REQUEST_FIELDS}
    }
  }
`;

export const REJECT_SHOP_ASSEMBLY_REQUEST = gql`
  mutation RejectShopAssemblyRequest($id: ID!, $reason: String) {
    rejectShopAssemblyRequest(id: $id, reason: $reason) {
      ${REQUEST_FIELDS}
    }
  }
`;

export const DISCARD_SHOP_ASSEMBLY_BATCH = gql`
  mutation DiscardShopAssemblyBatch($batchId: ID!) {
    discardShopAssemblyBatch(batchId: $batchId) {
      ${REQUEST_FIELDS}
    }
  }
`;
