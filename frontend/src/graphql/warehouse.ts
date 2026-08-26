import { gql } from '@apollo/client/core';

/**
 * What each product in a project can still be CLAIMED for (#342):
 * `availableQuantity = onHandQuantity - deficientQuantity - reservedQuantity`.
 *
 * This is the exact number the Start-a-Request creation gate applies server-side, so the wizard can
 * block an over-selection with per-combo detail before submission instead of bouncing the whole
 * finalize. Deliberately NOT the same as `inventoryHierarchy`'s availability (on-hand minus
 * deficient), which answers "what is physically unspoken-for in the building".
 */
export const GET_PROJECT_INVENTORY_AVAILABILITY = gql`
  query GetProjectInventoryAvailability($projectId: ID!) {
    projectInventoryAvailability(projectId: $projectId) {
      hardwareCategory
      productCode
      onHandQuantity
      deficientQuantity
      reservedQuantity
      availableQuantity
      classification
    }
  }
`;

// #506: the Hardware Items tab as one flat table rather than a category -> product -> location
// accordion. Every value the warehouse sorts, filters or exports on is on the row, resolved
// server-side in a single query.
export const GET_INVENTORY_ROWS = gql`
  query GetInventoryRows($projectId: ID, $warehouseId: ID) {
    inventoryRows(projectId: $projectId, warehouseId: $warehouseId) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId stockItemId warehouseId
        hardwareCategory productCode quantity deficientQuantity available
        aisle row bay receivedAt createdAt updatedAt
      }
      unitCost
      lineValue
      poNumber
      vendorName
      warehouseCode
      warehouseName
      projectNumber
      projectName
      matchesSchedule
    }
  }
`;

// Lean company-scale receiving picker (gp-owned-po mirror): rows carry two pending-quantity scalars
// from a grouped query instead of the line collection, so the list never materializes every line.
export const GET_OPEN_POS_SUMMARY = gql`
  query GetOpenPosSummary($projectId: ID) {
    openPosSummary(projectId: $projectId) {
      id
      poNumber
      projectId
      status
      origin
      gpVendorId
      vendorNameSnapshot
      notes
      orderedAt
      expectedDeliveryDate
      pendingLineCount
      pendingQuantity
    }
  }
`;

export const GET_UNLOCATED_INVENTORY = gql`
  query GetUnlocatedInventory($projectId: ID, $warehouseId: ID) {
    unlocatedInventory(projectId: $projectId, warehouseId: $warehouseId) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId warehouseId
        hardwareCategory productCode quantity
        aisle row bay receivedAt createdAt updatedAt
      }
      poNumber
      classification
      unitCost
    }
  }
`;

export const GET_RECENT_RECEIVE_RECORDS = gql`
  query GetRecentReceiveRecords($limit: Int) {
    recentReceiveRecords(limit: $limit) {
      receiveRecord {
        id
        poId
        receivedAt
        receivedBy
        # #447: GP's number for the receipt this receive posted, so the recent-activity row can be
        # matched against GP without going back through the PO and the timestamp.
        receiptNumber
        batchNumber
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
      poNumber
      totalItemsReceived
    }
  }
`;

/**
 * Every GP-registered PO with what has landed against it (#447) - the Receiving page's History view.
 *
 * Deliberately the complement of GET_OPEN_POS_SUMMARY and GET_BACK_ORDERED_ITEMS, which answer "what
 * is still owed" and so drop a PO the moment it is complete. Reconciling a delivery needs the finished
 * ones. Scalars only: expanding a row fetches that PO's receives through GET_PO_RECEIVING_DETAILS,
 * so the list stays one row per PO however many receives are behind it.
 */
export const GET_RECEIVING_HISTORY_POS = gql`
  query GetReceivingHistoryPos($projectId: ID) {
    receivingHistoryPos(projectId: $projectId) {
      id
      poNumber
      requestNumber
      status
      vendorName
      projectId
      orderedTotal
      receivedTotal
      receiveCount
      lastReceivedAt
    }
  }
`;

export const GET_PO_RECEIVING_DETAILS = gql`
  query GetPOReceivingDetails($poId: ID!) {
    poReceivingDetails(poId: $poId) {
      id
      poNumber
      requestNumber
      # #425: the receive modal joins this to the projects list to find out whether the PO's GP job is
      # quarantined. A broken job's receipt is rejected by eConnect with "Invalid Account Index", so
      # the modal has to say so before the warehouse user finishes counting.
      projectId
      gpCompany
      gpVendorId
      vendorNameSnapshot
      notes
      status
      lineItems {
        id
        poId
        hardwareCategory
        productCode
        classification
        orderedQuantity
        receivedQuantity
        unitCost
        orderAs
        gpLineOrd
      }
      receiveRecords {
        id
        receivedAt
        receivedBy
        # #447: the History view expands a PO through this query, and each receive names the GP
        # receipt it posted.
        receiptNumber
        batchNumber
        # #632: the counter's remark, carried off the approved draft.
        notes
        lineItems {
          id
          poLineItemId
          hardwareCategory
          productCode
          quantityReceived
        }
      }
    }
  }
`;

export const GET_PULL_REQUESTS = gql`
  query GetPullRequests(
    $projectId: ID
    $source: PullRequestSource
    $status: PullRequestStatus
    $statuses: [PullRequestStatus!]
  ) {
    pullRequests(projectId: $projectId, source: $source, status: $status, statuses: $statuses) {
      id
      requestNumber
      projectId
      source
      status
      requestedBy
      assignedTo
      createdAt
      updatedAt
      approvedAt
      completedAt
      cancelledAt
      cancelledBy
      cancellationReason
      # The pick (#367). pickedAt is the moment stock left; partiallyPicked is "a short confirm is
      # outstanding" and is only computed for un-picked pulls.
      pickedAt
      pickedBy
      partiallyPicked
      items {
        id
        pullRequestId
        openingNumber
        hardwareCategory
        productCode
        requestedQuantity
      }
    }
  }
`;

export const GET_LOCATION_UTILIZATION = gql`
  query GetLocationUtilization($warehouseId: ID) {
    locationUtilization(warehouseId: $warehouseId) {
      warehouseId
      aisle
      row
      bay
      itemCount
      totalQuantity
    }
  }
`;

export const GET_LOCATION_CONTENTS = gql`
  query GetLocationContents($aisle: String!, $row: String, $bay: String, $warehouseId: ID) {
    locationContents(aisle: $aisle, row: $row, bay: $bay, warehouseId: $warehouseId) {
      inventoryItems {
        inventoryLocation {
          id projectId poLineItemId receiveLineItemId stockItemId warehouseId
          hardwareCategory productCode quantity deficientQuantity available
          aisle row bay receivedAt createdAt updatedAt
        }
        poNumber
        unitCost
      }
      stockItems {
        id warehouseId hardwareCategory productCode quantity deficientQuantity available
        aisle row bay receivedAt createdAt updatedAt
      }
    }
  }
`;

export const GET_LOCATION_AUDIT_HISTORY = gql`
  query GetLocationAuditHistory($aisle: String!, $row: String, $bay: String, $limit: Int, $warehouseId: ID) {
    locationAuditHistory(aisle: $aisle, row: $row, bay: $bay, limit: $limit, warehouseId: $warehouseId) {
      id projectId entityType entityId action detail performedBy createdAt
    }
  }
`;

export const GET_LOCATION_DISTINCT_VALUES = gql`
  query GetLocationDistinctValues {
    locationDistinctValues {
      aisles
      rows
      bays
    }
  }
`;

export const GET_BACK_ORDERED_ITEMS = gql`
  query GetBackOrderedItems($projectId: ID) {
    backOrderedItems(projectId: $projectId) {
      poLineItemId
      hardwareCategory
      productCode
      orderedQuantity
      receivedQuantity
      outstandingQuantity
      poNumber
      vendorName
      expectedDeliveryDate
      projectName
    }
  }
`;

export const GET_WAREHOUSE_DASHBOARD = gql`
  query GetWarehouseDashboard {
    warehouseDashboard {
      totalItemCount
      totalValue
      unlocatedCount
      stockItemCount
      stockValue
      stockUnlocatedCount
      pendingPullShop
      pendingPullShipping
      backOrderedPoCount
      deficientCount
      pendingReceiveDraftCount
    }
  }
`;

export const GET_STOCK_ITEMS = gql`
  query GetStockItems(
    $productCodeContains: String
    $hardwareCategory: String
    $aisle: String
    $onlyDeficient: Boolean
    $warehouseId: ID
    $onlyUnlocated: Boolean
  ) {
    stockItems(
      productCodeContains: $productCodeContains
      hardwareCategory: $hardwareCategory
      aisle: $aisle
      onlyDeficient: $onlyDeficient
      warehouseId: $warehouseId
      onlyUnlocated: $onlyUnlocated
    ) {
      id
      warehouseId
      hardwareCategory
      productCode
      quantity
      deficientQuantity
      available
      unitCost
      aisle
      row
      bay
      receivedAt
      createdAt
      updatedAt
    }
  }
`;

export const GET_STOCK_ITEM = gql`
  query GetStockItem($id: ID!) {
    stockItem(id: $id) {
      id
      hardwareCategory
      productCode
      quantity
      deficientQuantity
      available
      aisle
      row
      bay
      receivedAt
      createdAt
      updatedAt
    }
  }
`;

export const GET_DEFICIENT_ITEMS = gql`
  query GetDeficientItems($projectId: ID, $source: DeficientItemSource) {
    deficientItems(projectId: $projectId, source: $source) {
      source
      inventoryLocationId
      stockItemId
      projectId
      hardwareCategory
      productCode
      deficientQuantity
      aisle
      row
      bay
    }
  }
`;

export const GET_DEFICIENCY_REVIEWS = gql`
  query GetDeficiencyReviews($inventoryLocationId: ID, $stockItemId: ID, $projectId: ID) {
    deficiencyReviews(
      inventoryLocationId: $inventoryLocationId
      stockItemId: $stockItemId
      projectId: $projectId
    ) {
      id
      inventoryLocationId
      stockItemId
      resolution
      quantity
      reasonText
      rmaReference
      reviewedBy
      reviewedAt
      resultingStockItemId
    }
  }
`;

export const ADJUST_INVENTORY_QUANTITY = gql`
  mutation AdjustInventoryQuantity(
    $inventoryLocationId: ID!
    $adjustment: Int!
    $reason: String!
    $spotCheck: Boolean
  ) {
    adjustInventoryQuantity(
      inventoryLocationId: $inventoryLocationId
      adjustment: $adjustment
      reason: $reason
      spotCheck: $spotCheck
    ) {
      id
      projectId
      poLineItemId
      receiveLineItemId
      hardwareCategory
      productCode
      quantity
      deficientQuantity
      available
      aisle
      row
      bay
      receivedAt
      createdAt
      updatedAt
    }
  }
`;

// --- Defined-locations registry (#632) ---
//
// The put-away pickers read the ACTIVE registry and every location write is validated against it
// server-side; the Locations tab reads everything so deactivated rows stay manageable.

export const GET_WAREHOUSE_LOCATIONS = gql`
  query GetWarehouseLocations($warehouseId: ID, $activeOnly: Boolean) {
    warehouseLocations(warehouseId: $warehouseId, activeOnly: $activeOnly) {
      id
      warehouseId
      aisle
      row
      bay
      active
      createdAt
    }
  }
`;

export const CREATE_WAREHOUSE_LOCATION = gql`
  mutation CreateWarehouseLocation($warehouseId: ID!, $aisle: String!, $row: String!, $bay: String!) {
    createWarehouseLocation(warehouseId: $warehouseId, aisle: $aisle, row: $row, bay: $bay) {
      id
      warehouseId
      aisle
      row
      bay
      active
      createdAt
    }
  }
`;

export const DEACTIVATE_WAREHOUSE_LOCATION = gql`
  mutation DeactivateWarehouseLocation($id: ID!) {
    deactivateWarehouseLocation(id: $id) {
      id
      active
    }
  }
`;

// --- Drafted receives and the approval that posts them ---
//
// A receive is two actions now. `createReceiveDraft` records what somebody counted and reaches
// neither GP nor inventory; `approveReceiveDraft` is the GP-first pipeline `createReceive` used to
// be, moved behind a Warehouse Manager.

// Shared selection so a draft read from a mutation result is cache-identical to the queue's rows.
const RECEIVE_DRAFT_FIELDS = `
  id
  status
  poId
  poNumber
  projectId
  warehouseId
  # The Clerk id and the display name of whoever counted the hardware. The id is what "my drafts"
  # and the author-only actions key on; the name is what the manager's queue shows.
  createdByUserId
  createdBy
  # #504: the packing slip this count was made against. Null only on drafts raised before the
  # requirement existed.
  packingSlipDocumentId
  reviewedBy
  reviewedAt
  rejectionReason
  # What an in-flight approval is holding the draft under, so a reviewer whose approval died
  # ambiguously can retry with the SAME key and resume rather than start a second one.
  approvalIdempotencyKey
  receiveRecordId
  outboxEntryId
  # #632: the counter's remark for the approver ("box crushed"). Carried onto the record at approval.
  notes
  totalQuantity
  createdAt
  updatedAt
  lineItems {
    id
    poLineItemId
    hardwareCategory
    productCode
    quantityReceived
    locations { aisle row bay quantity deficientQuantity }
  }
`;

export const GET_RECEIVE_DRAFTS = gql`
  query GetReceiveDrafts($status: ReceiveDraftStatus, $poId: ID, $mine: Boolean) {
    receiveDrafts(status: $status, poId: $poId, mine: $mine) { ${RECEIVE_DRAFT_FIELDS} }
  }
`;

// Scalars only, for the Receiving page's "already counted" chip and the approvals badge. Those want
// a count per PO and nothing else, and the full selection above would make the backend build every
// line and rack row of every pending draft in the system on each page load (CLAUDE.md perf rule 3).
// Apollo normalises both on `id`, so this coexists with the full read rather than competing with it.
export const GET_PENDING_DRAFT_SUMMARIES = gql`
  query GetPendingDraftSummaries {
    receiveDrafts(status: PENDING_APPROVAL) {
      id
      poId
      totalQuantity
    }
  }
`;

export const CREATE_RECEIVE_DRAFT = gql`
  mutation CreateReceiveDraft($input: CreateReceiveDraftInput!) {
    createReceiveDraft(input: $input) { ${RECEIVE_DRAFT_FIELDS} }
  }
`;

export const UPDATE_RECEIVE_DRAFT = gql`
  mutation UpdateReceiveDraft($input: UpdateReceiveDraftInput!) {
    updateReceiveDraft(input: $input) { ${RECEIVE_DRAFT_FIELDS} }
  }
`;

export const RESUBMIT_RECEIVE_DRAFT = gql`
  mutation ResubmitReceiveDraft($id: ID!) {
    resubmitReceiveDraft(id: $id) { ${RECEIVE_DRAFT_FIELDS} }
  }
`;

export const REJECT_RECEIVE_DRAFT = gql`
  mutation RejectReceiveDraft($input: RejectReceiveDraftInput!) {
    rejectReceiveDraft(input: $input) { ${RECEIVE_DRAFT_FIELDS} }
  }
`;

export const DELETE_RECEIVE_DRAFT = gql`
  mutation DeleteReceiveDraft($id: ID!) {
    deleteReceiveDraft(id: $id)
  }
`;

// Deliberately the same wrapper the old CREATE_RECEIVE returned (#353 PR E), because it reports the
// same moment: `queued` true means the GP relay was unreachable and the receipt is on the durable
// outbox - `receiveRecord` is null because the UC Nexus receive is persisted together with the GP
// write, so nothing is in inventory yet.
export const APPROVE_RECEIVE_DRAFT = gql`
  mutation ApproveReceiveDraft($input: ApproveReceiveDraftInput!) {
    approveReceiveDraft(input: $input) {
      queued
      outboxEntryId
      draft { ${RECEIVE_DRAFT_FIELDS} }
      receiveRecord {
        id
        poId
        receivedAt
        receivedBy
        # #447: what the success screen shows back so the user can write the GP receipt on the
        # packing slip without going and looking it up.
        receiptNumber
        batchNumber
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
  }
`;

// Shared shape so a pull read from a mutation result is cache-identical to one read from the queue.
const PULL_REQUEST_FIELDS = `
  id requestNumber projectId source status requestedBy assignedTo
  createdAt updatedAt approvedAt completedAt cancelledAt cancelledBy cancellationReason
  pickedAt pickedBy partiallyPicked
  items {
    id pullRequestId openingNumber hardwareCategory productCode requestedQuantity
  }
`;

// The pick screen and the printed sheet (#367). Note what is absent: any suggested quantity. The
// picker decides, and the sheet gives them received dates so they can rotate stock themselves.
const PICK_SHEET_FIELDS = `
  pullRequest { ${PULL_REQUEST_FIELDS} }
  sections {
    hardwareCategory productCode requiredQuantity appliedQuantity remainingQuantity
    claimableQuantity claimableShortfall
    openings { openingNumber quantity }
    locations {
      inventoryLocationId warehouseId warehouseCode aisle row bay
      available receivedAt draftQuantity appliedQuantity orderAs poNumber
    }
  }
`;

// #427: who did it is taken from the Clerk token server-side, so these mutations no longer send an
// actor. The arguments still exist in the schema (accepted and ignored) so a tab loaded against the
// previous deploy keeps working; they are dropped once no deployed frontend references them.
export const START_PULL_REQUEST_PICK = gql`
  mutation StartPullRequestPick($id: ID!) {
    startPullRequestPick(id: $id) { ${PULL_REQUEST_FIELDS} }
  }
`;

export const GET_PULL_PICK_SHEET = gql`
  query GetPullPickSheet($pullRequestId: ID!) {
    pullPickSheet(pullRequestId: $pullRequestId) { ${PICK_SHEET_FIELDS} }
  }
`;

export const SAVE_PICK_DRAFT = gql`
  mutation SavePickDraft($pullRequestId: ID!, $lines: [PickLineInput!]!) {
    savePickDraft(pullRequestId: $pullRequestId, lines: $lines) {
      ${PICK_SHEET_FIELDS}
    }
  }
`;

export const CONFIRM_PICK = gql`
  mutation ConfirmPick($pullRequestId: ID!, $lines: [PickLineInput!]!) {
    confirmPick(pullRequestId: $pullRequestId, lines: $lines) {
      pullRequest { ${PULL_REQUEST_FIELDS} }
      outcome
      appliedQuantity
      notification {
        id projectId recipientRole type message isRead createdAt
      }
      shortfalls {
        hardwareCategory productCode requested available short reserved
      }
    }
  }
`;

export const COMPLETE_PULL_REQUEST = gql`
  mutation CompletePullRequest($id: ID!) {
    completePullRequest(id: $id) { ${PULL_REQUEST_FIELDS} }
  }
`;

export const CANCEL_PULL_REQUEST = gql`
  mutation CancelPullRequest($input: CancelPullRequestInput!) {
    cancelPullRequest(input: $input) {
      pullRequest { ${PULL_REQUEST_FIELDS} }
      restocked { hardwareCategory productCode quantity }
      sourceRequestReturnedToPending
      reservationsRecreated
      integrityNote
    }
  }
`;

export const TRANSFER_INVENTORY = gql`
  mutation TransferInventory($input: TransferInventoryInput!) {
    transferInventory(input: $input) {
      success
      quantity
      destWarehouseId
    }
  }
`;

// ---------------------------------------------------------------------------
// Stock pool + deficiency mutations
// ---------------------------------------------------------------------------

export const DESTOCK_INVENTORY = gql`
  mutation DestockInventory($input: DestockInventoryInput!) {
    destockInventory(input: $input) {
      id hardwareCategory productCode quantity deficientQuantity available
      aisle row bay receivedAt
    }
  }
`;

export const ALLOCATE_STOCK_TO_PROJECT = gql`
  mutation AllocateStockToProject($input: AllocateStockToProjectInput!) {
    allocateStockToProject(input: $input) {
      id projectId hardwareCategory productCode quantity deficientQuantity available
      aisle row bay receivedAt
    }
  }
`;

export const ADJUST_STOCK_QUANTITY = gql`
  mutation AdjustStockQuantity($input: AdjustStockQuantityInput!) {
    adjustStockQuantity(input: $input) {
      id hardwareCategory productCode quantity deficientQuantity available
    }
  }
`;

export const MOVE_STOCK_LOCATION = gql`
  mutation MoveStockLocation($input: MoveStockLocationInput!) {
    moveStockLocation(input: $input) {
      id aisle row bay
    }
  }
`;

export const ASSIGN_STOCK_ITEM_LOCATION = gql`
  mutation AssignStockItemLocation($stockItemId: ID!, $aisle: String!, $row: String!, $bay: String!) {
    assignStockItemLocation(stockItemId: $stockItemId, aisle: $aisle, row: $row, bay: $bay) {
      id aisle row bay
    }
  }
`;

export const MARK_STOCK_ITEM_UNLOCATED = gql`
  mutation MarkStockItemUnlocated($stockItemId: ID!) {
    markStockItemUnlocated(stockItemId: $stockItemId) {
      id aisle row bay
    }
  }
`;

export const RECLASSIFY_STOCK_ITEM = gql`
  mutation ReclassifyStockItem($input: ReclassifyStockItemInput!) {
    reclassifyStockItem(input: $input) {
      reclassifiedStockItem {
        id hardwareCategory productCode quantity deficientQuantity available
        aisle row bay
      }
      originalStockItem {
        id hardwareCategory productCode quantity deficientQuantity available
        aisle row bay
      }
    }
  }
`;

export const REPORT_INVENTORY_DEFICIENCY = gql`
  mutation ReportInventoryDeficiency($input: ReportInventoryDeficiencyInput!) {
    reportInventoryDeficiency(input: $input) {
      id quantity deficientQuantity available
    }
  }
`;

export const REPORT_STOCK_DEFICIENCY = gql`
  mutation ReportStockDeficiency($input: ReportStockDeficiencyInput!) {
    reportStockDeficiency(input: $input) {
      id quantity deficientQuantity available
    }
  }
`;

export const RESOLVE_DEFICIENCY = gql`
  mutation ResolveDeficiency($input: ResolveDeficiencyInput!) {
    resolveDeficiency(input: $input) {
      id inventoryLocationId stockItemId resolution quantity reasonText
      rmaReference reviewedBy reviewedAt resultingStockItemId
    }
  }
`;

// #505: every receive entity in one list - drafts pending approval, drafts being approved,
// rejected drafts and booked records. The existing views each cover a slice, and a rejected draft
// appeared in none of them.
export const GET_RECEIVES = gql`
  query GetReceives($limit: Int, $offset: Int, $projectId: ID, $poSearch: String) {
    receives(limit: $limit, offset: $offset, projectId: $projectId, poSearch: $poSearch) {
      kind
      id
      occurredAt
      status
      poId
      poNumber
      projectId
      projectName
      lineCount
      totalQuantity
      countedBy
      reviewedBy
      rejectionReason
      receiptNumber
      batchNumber
    }
  }
`;
