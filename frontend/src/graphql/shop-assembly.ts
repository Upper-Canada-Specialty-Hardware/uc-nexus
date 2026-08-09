import { gql } from '@apollo/client/core';

export const GET_SHOP_ASSEMBLY_STATS = gql`
  query GetShopAssemblyStats {
    shopAssemblyStats {
      activePullRequestCount
    }
  }
`;

// The requests list, which is the whole of shop assembly in v1: a request is composed, accepted,
// pulled, and the completed pull is where the system stops following the hardware. `stage` is the
// column the list groups by and is derived server-side in one query for the page.
export const GET_SHOP_ASSEMBLY_REQUESTS = gql`
  query GetShopAssemblyRequests($projectId: ID, $status: ShopAssemblyRequestStatus, $reopenableOnly: Boolean) {
    shopAssemblyRequests(projectId: $projectId, status: $status, reopenableOnly: $reopenableOnly) {
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
      pullRequestId
      items {
        id
        openingNumber
        hardwareCategory
        productCode
        quantity
        allocatedQuantity
      }
    }
  }
`;

const REQUEST_RESULT_FIELDS = `
  id
  status
  stage
  approvedBy
  approvedAt
  rejectedBy
  rejectedAt
  rejectionReason
  pullRequestId`;

export const ACCEPT_SHOP_ASSEMBLY_REQUEST = gql`
  mutation AcceptShopAssemblyRequest($id: ID!) {
    acceptShopAssemblyRequest(id: $id) {
      ${REQUEST_RESULT_FIELDS}
    }
  }
`;

export const REJECT_SHOP_ASSEMBLY_REQUEST = gql`
  mutation RejectShopAssemblyRequest($id: ID!, $reason: String) {
    rejectShopAssemblyRequest(id: $id, reason: $reason) {
      ${REQUEST_RESULT_FIELDS}
    }
  }
`;

export const REOPEN_SHOP_ASSEMBLY_REQUEST = gql`
  mutation ReopenShopAssemblyRequest($id: ID!) {
    reopenShopAssemblyRequest(id: $id) {
      ${REQUEST_RESULT_FIELDS}
    }
  }
`;
