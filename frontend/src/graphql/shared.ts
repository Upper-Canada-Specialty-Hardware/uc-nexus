import { gql } from '@apollo/client/core';

// gpSetupOk / gpSetupIssues (#425) ride along on every project read: they are scalar columns on the
// project row (no relationship walk, no N+1), and every module that lets a user pick a project has to
// be able to badge a quarantined one rather than discovering it at the submit button.
const PICKER_PROJECT_FIELDS = `
      id
      projectId
      description
      client
      jobSiteName
      # #632: the XML the schedule on file came from, shown on the project landing card. Null on
      # projects last imported before the name was captured (#627) - the card omits the line.
      scheduleFilename
      # #637: the GP company (tenant) that owns the job. Every row is the caller's acting company since
      # #845; read so a GP-writing screen can name the company a pick writes into.
      company
      openingCount
      gpSetupOk
      gpSetupCheckedAt
      gpSetupIssues {
        costCode
        accountIndex
      }
      # #730: inactive, closed or missing in GP. Tagged in every picker, and the GP-bound ones grey it out.
      gpJobState
`;

export const GET_PROJECTS = gql`
  query GetProjects {
    projects {
      ${PICKER_PROJECT_FIELDS}
    }
  }
`;

// #1877: one project by its id, archived included, with the picker's fields - for a screen scoped to
// a project by a link, where `projects` (which leaves archived jobs out) cannot fill the picker.
export const GET_PROJECT = gql`
  query GetProject($id: ID!) {
    project(id: $id) {
      ${PICKER_PROJECT_FIELDS}
    }
  }
`;

export const GET_PRIOR_ORDER_AS_VALUES = gql`
  query GetPriorOrderAsValues($projectId: ID, $productCodes: [String!]!) {
    priorOrderAsValues(projectId: $projectId, productCodes: $productCodes) {
      productCode
      values
    }
  }
`;

// The bell's one poll (#1894): the latest few and the unread count ride together, so every open tab
// makes one request a tick rather than two. #1112: the badge reads the count, not the length of a
// capped list.
export const GET_NOTIFICATION_BELL = gql`
  query GetNotificationBell($limit: Int) {
    notifications(limit: $limit) {
      id
      projectId
      recipientRole
      type
      message
      isRead
      createdAt
    }
    notificationUnreadCount
  }
`;

// #637: `companies`, not `company` - the relay reports every GP company its company master gives
// it, and every screen that used to read the single value now picks from this list.
//
// The link-health scalars below feed the Relay Installs status strip. They ride along on the one
// shared relayStatus document on purpose: a second document selecting a different subset of this
// (un-normalized) root field would replace it in the cache on every poll instead of merging.
// gpCompanies is the same list with GP's own display name on each code, and companiesError says why a
// connected relay reported none.
export const GET_RELAY_STATUS = gql`
  query GetRelayStatus {
    relayStatus {
      connected
      companies
      gpCompanies {
        id
        name
      }
      companiesError
      build
      installId
      lastConnectedAt
      lastDisconnectedAt
      lastDisconnectReason
    }
  }
`;

// #845: the GP companies a UC NEXUS ADMIN can switch between - every company the relay serves plus
// every company that holds a project, sorted by code. Admin only; a scoped user never asks.
export const GET_NEXUS_COMPANIES = gql`
  query GetNexusCompanies {
    nexusCompanies {
      id
      name
    }
  }
`;

// The GP write queue (#353 PR E). The summary is polled by the queue chip; the list is read by the
// admin queue table and by the PO lists, which join entries onto rows client-side on `entityKey`.
export const GET_GP_OUTBOX_SUMMARY = gql`
  query GetGpOutboxSummary {
    gpOutboxSummary {
      pending
      inFlight
      failed
      oldestPendingAt
      lastDrainedAt
      lastSettledAt
    }
  }
`;

// `ops` narrows the list to particular relay operations (#754), so a module can show only the writes
// it is responsible for - `create_po` on the PO table, `create_receipt` on Receiving - while the
// admin queue asks for all of them.
export const GET_GP_OUTBOX = gql`
  query GetGpOutbox(
    $status: GpOutboxStatus
    $limit: Int
    $ops: [String!]
    $statuses: [GpOutboxStatus!]
    $holdingDrafts: Boolean
  ) {
    gpOutbox(status: $status, limit: $limit, ops: $ops, statuses: $statuses, holdingDrafts: $holdingDrafts) {
      id
      label
      op
      relayOp
      company
      status
      attempts
      nextAttemptAt
      lastError
      failureKind
      entityKey
      createdAt
      # #1948: a PO registration that still holds its draft, FAILED ones included.
      holdsDraft
      # #1948: GP took the write (no Cancel), or may have (Cancel warns to check GP first).
      gpTook
      maybeInGp
      # #1948: a registration GP took whose GP PO the mirror already copied into Nexus - let go with Cancel.
      alreadyInNexusAs
      # #1961: a receipt GP took whose draft has moved on - GP holds it, Nexus booked nothing; Cancel lets it go.
      receiptDraftMovedOn
    }
  }
`;

export const GET_WAREHOUSES = gql`
  query GetWarehouses($includeInactive: Boolean) {
    warehouses(includeInactive: $includeInactive) {
      id
      name
      code
      # #637: the GP company the building belongs to.
      company
      address
      city
      province
      postalCode
      isPrimary
      isActive
      createdAt
      updatedAt
    }
  }
`;

export const GET_AUDIT_LOG = gql`
  query GetAuditLog(
    $entityId: ID
    $entityType: AuditEntityType
    $projectId: ID
    $limit: Int
    $offset: Int
    $beforeId: ID
  ) {
    auditLog(
      entityId: $entityId
      entityType: $entityType
      projectId: $projectId
      limit: $limit
      offset: $offset
      beforeId: $beforeId
    ) {
      id
      projectId
      entityType
      entityId
      action
      detail
      performedBy
      createdAt
    }
  }
`;

export const MOVE_INVENTORY_LOCATION = gql`
  mutation MoveInventoryLocation($inventoryLocationId: ID!, $newAisle: String!, $newRow: String!, $newBay: String!) {
    moveInventoryLocation(inventoryLocationId: $inventoryLocationId, newAisle: $newAisle, newRow: $newRow, newBay: $newBay) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

export const MARK_INVENTORY_UNLOCATED = gql`
  mutation MarkInventoryUnlocated($inventoryLocationId: ID!) {
    markInventoryUnlocated(inventoryLocationId: $inventoryLocationId) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

export const ASSIGN_INVENTORY_LOCATION = gql`
  mutation AssignInventoryLocation($inventoryLocationId: ID!, $aisle: String!, $row: String!, $bay: String!) {
    assignInventoryLocation(inventoryLocationId: $inventoryLocationId, aisle: $aisle, row: $row, bay: $bay) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

/**
 * Break units off an unlocated row so they can go on a different shelf (#501).
 *
 * Put-away happens after the warehouse manager approves now, so a receive books one row per PO
 * line. Ten hinges arriving as one row routinely go to two bins, and a row carries exactly one
 * aisle/row/bay. Returns [original, new]; the new row is unlocated and is what gets assigned next.
 */
export const SPLIT_INVENTORY_LOCATION = gql`
  mutation SplitInventoryLocation($inventoryLocationId: ID!, $quantity: Int!) {
    splitInventoryLocation(inventoryLocationId: $inventoryLocationId, quantity: $quantity) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle row bay receivedAt createdAt updatedAt
    }
  }
`;

export const MARK_NOTIFICATION_AS_READ = gql`
  mutation MarkNotificationAsRead($id: ID!) {
    markNotificationAsRead(id: $id) {
      id
      isRead
    }
  }
`;

export const MARK_ALL_NOTIFICATIONS_AS_READ = gql`
  mutation MarkAllNotificationsAsRead {
    markAllNotificationsAsRead
  }
`;
