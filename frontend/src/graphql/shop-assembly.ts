import { gql } from '@apollo/client/core';

// Shop-assembly team members for the manager assignment picker (#330). Manager-gated backend query.
export const GET_SHOP_ASSEMBLY_MEMBERS = gql`
  query GetShopAssemblyMembers {
    shopAssemblyMembers {
      id
      firstName
      lastName
      email
      roles
      imageUrl
    }
  }
`;

export const GET_ASSEMBLE_LIST = gql`
  query GetAssembleList($projectId: ID) {
    assembleList(projectId: $projectId) {
      id
      shopAssemblyRequestId
      pullRequestId
      openingId
      pullStatus
      assignedToUserId
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      leaf
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
        allocatedQuantity
        installedQuantity
        deficientQuantity
        replacementPendingQuantity
      }
    }
  }
`;

export const GET_MY_WORK = gql`
  query GetMyWork($assignedToUserId: String!) {
    myWork(assignedToUserId: $assignedToUserId) {
      id
      shopAssemblyRequestId
      pullRequestId
      openingId
      pullStatus
      assignedToUserId
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      leaf
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
        allocatedQuantity
        installedQuantity
        deficientQuantity
        replacementPendingQuantity
      }
    }
  }
`;

// Replacement installs outstanding on already-completed leaves (#341). Scoped to one assembler so it
// lands in the My Work board of whoever last held the leaf - the opening keeps its assignment through
// completion, so this needs no new assignment concept. Rows whose openingItemState is SHIPPED_OUT are
// listed deliberately: that replacement must stay visible rather than be stranded, even though it
// cannot be installed.
export const GET_REPLACEMENT_WORK = gql`
  query GetReplacementWork($assignedToUserId: String, $projectId: ID) {
    replacementWork(assignedToUserId: $assignedToUserId, projectId: $projectId) {
      shopAssemblyOpeningItemId
      shopAssemblyOpeningId
      projectId
      openingNumber
      leaf
      building
      floor
      hardwareCategory
      productCode
      pendingQuantity
      assignedToUserId
      assignedTo
      openingItemId
      openingItemState
    }
  }
`;

// Fit arrived replacement hardware to a finished leaf (#341) - the one legitimate write to an
// assembled leaf's hardware after completion. Returns the leaf so the caller can see its updated
// installedHardware and whether anything is still owed to it.
export const INSTALL_REPLACEMENT = gql`
  mutation InstallReplacement($input: InstallReplacementInput!) {
    installReplacement(input: $input) {
      id
      openingNumber
      leaf
      state
      awaitingReplacementQuantity
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

// The pipeline rollup, one row per shop-assembly request (#344). Answers "how far has this request
// got" for a project, or for every project when projectId is omitted - the backend runs a fixed five
// statements either way, so the All-Projects view is a normal read rather than a special case.
const PIPELINE_SUMMARY_FIELDS = `
  requestId
  requestNumber
  projectId
  projectCode
  projectName
  requestStatus
  createdBy
  createdAt
  acceptedBy
  acceptedAt
  rejectedBy
  rejectedAt
  integrityNote
  pullRequestId
  pullRequestStatus
  pullApprovedAt
  pullCompletedAt
  stagingStatus
  cancelledPullCount
  lastCancelledAt
  lastCancelledBy
  lastCancellationReason
  openingCount
  stagedOpeningCount
  assignedOpeningCount
  inProgressOpeningCount
  completedOpeningCount
  shippedOpeningCount
  plannedUnitCount
  allocatedUnitCount
  shortUnitCount
  installedUnitCount
  deficientUnitCount
  replacementPendingUnitCount
  awaitingReplacementOpeningCount
  replacementAfterShipOpeningCount
  shortOpeningCount
  stage
`;

export const GET_ASSEMBLY_PIPELINE_SUMMARIES = gql`
  query GetAssemblyPipelineSummaries($projectId: ID, $status: ShopAssemblyRequestStatus) {
    assemblyPipelineSummaries(projectId: $projectId, status: $status) {
      ${PIPELINE_SUMMARY_FIELDS}
    }
  }
`;

// One request down to the individual door leaf: the query that answers "where is opening A01 leaf 2?"
// in one place instead of four. The header counts are the same aggregates the list above uses, so the
// two screens cannot disagree.
export const GET_ASSEMBLY_PIPELINE = gql`
  query GetAssemblyPipeline($requestId: ID!) {
    assemblyPipeline(requestId: $requestId) {
      summary {
        ${PIPELINE_SUMMARY_FIELDS}
      }
      openings {
        shopAssemblyOpeningId
        openingNumber
        leaf
        building
        floor
        location
        stage
        pullStatus
        stagedAt
        stagedBy
        assignedToUserId
        assignedTo
        assemblyStatus
        completedAt
        plannedUnitCount
        allocatedUnitCount
        shortUnitCount
        installedUnitCount
        deficientUnitCount
        replacementPendingUnitCount
        awaitingReplacementUnitCount
        replacementArrivedAfterShip
        openingItemId
        openingItemState
        assembledLocation
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
  query GetShopAssemblyRequests($projectId: ID, $status: ShopAssemblyRequestStatus, $reopenableOnly: Boolean) {
    shopAssemblyRequests(projectId: $projectId, status: $status, reopenableOnly: $reopenableOnly) {
      id
      requestNumber
      projectId
      status
      createdBy
      createdAt
      integrityNote
      openings {
        id
        openingNumber
        building
        floor
        leaf
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

export const REOPEN_SHOP_ASSEMBLY_REQUEST = gql`
  mutation ReopenShopAssemblyRequest($id: ID!) {
    reopenShopAssemblyRequest(id: $id) {
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
      assignedToUserId
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      leaf
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
        allocatedQuantity
        installedQuantity
        deficientQuantity
        replacementPendingQuantity
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
      assignedToUserId
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      leaf
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
        allocatedQuantity
        installedQuantity
        deficientQuantity
        replacementPendingQuantity
      }
    }
  }
`;

// Save partial assembly progress without finishing the leaf (#340). Returns the opening so the modal
// can re-hydrate from what the server actually stored - installedQuantity is absolute, and a
// flagDeficientQuantity line has already minted a replacement pull by the time this resolves.
export const RECORD_ASSEMBLY_PROGRESS = gql`
  mutation RecordAssemblyProgress($input: RecordAssemblyProgressInput!) {
    recordAssemblyProgress(input: $input) {
      id
      shopAssemblyRequestId
      pullRequestId
      openingId
      pullStatus
      assignedToUserId
      assignedTo
      assemblyStatus
      completedAt
      openingNumber
      building
      floor
      leaf
      items {
        id
        shopAssemblyOpeningId
        hardwareCategory
        productCode
        quantity
        allocatedQuantity
        installedQuantity
        deficientQuantity
        replacementPendingQuantity
      }
    }
  }
`;

// CompleteOpeningInput has no itemResults since #340 - completion reads the persisted per-item
// progress, so the client no longer restates what was installed at the moment it finishes.
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
      leaf
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
