import { gql } from '@apollo/client/core';

export const GET_ASSEMBLE_LIST = gql`
  query GetAssembleList($projectId: ID) {
    assembleList(projectId: $projectId) {
      id
      shopAssemblyRequestId
      pullRequestId
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

export const GET_MY_WORK = gql`
  query GetMyWork($assignedTo: String!) {
    myWork(assignedTo: $assignedTo) {
      id
      shopAssemblyRequestId
      pullRequestId
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

export const GET_SHOP_ASSEMBLY_STATS = gql`
  query GetShopAssemblyStats {
    shopAssemblyStats {
      activePullRequestCount
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
      createdAt
      openings {
        id
        openingNumber
        building
        floor
        items {
          id
          hardwareCategory
          productCode
          quantity
        }
      }
    }
  }
`;

export const ACCEPT_SHOP_ASSEMBLY_REQUEST = gql`
  mutation AcceptShopAssemblyRequest($id: ID!, $acceptedBy: String!) {
    acceptShopAssemblyRequest(id: $id, acceptedBy: $acceptedBy) {
      id
      status
    }
  }
`;

export const REJECT_SHOP_ASSEMBLY_REQUEST = gql`
  mutation RejectShopAssemblyRequest($id: ID!, $rejectedBy: String!, $reason: String) {
    rejectShopAssemblyRequest(id: $id, rejectedBy: $rejectedBy, reason: $reason) {
      id
      status
    }
  }
`;

export const ASSIGN_OPENINGS = gql`
  mutation AssignOpenings($input: AssignOpeningsInput!) {
    assignOpenings(input: $input) {
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

export const REMOVE_OPENING_FROM_USER = gql`
  mutation RemoveOpeningFromUser($openingId: ID!) {
    removeOpeningFromUser(openingId: $openingId) {
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

export const COMPLETE_OPENING = gql`
  mutation CompleteOpening($input: CompleteOpeningInput!) {
    completeOpening(input: $input) {
      id
      projectId
      openingId
      openingNumber
      building
      floor
      location
      quantity
      assemblyCompletedAt
      state
      aisle
      row
      bay
      createdAt
      updatedAt
      installedHardware {
        id
        openingItemId
        productCode
        hardwareCategory
        quantity
      }
    }
  }
`;
