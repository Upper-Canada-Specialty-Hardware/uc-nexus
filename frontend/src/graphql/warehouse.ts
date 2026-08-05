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
    }
  }
`;

export const GET_INVENTORY_HIERARCHY = gql`
  query GetInventoryHierarchy($projectId: ID, $warehouseId: ID) {
    inventoryHierarchy(projectId: $projectId, warehouseId: $warehouseId) {
      hardwareCategory
      totalQuantity
      totalAvailableQuantity
      totalValue
      productCodes {
        productCode
        totalQuantity
        totalAvailableQuantity
        totalValue
        matchesSchedule
        items {
          id
          projectId
          poLineItemId
          receiveLineItemId
          hardwareCategory
          productCode
          quantity
          aisle
          row
          bay
          receivedAt
          createdAt
          updatedAt
        }
      }
    }
  }
`;

export const GET_INVENTORY_ITEMS = gql`
  query GetInventoryItems($projectId: ID, $category: String!, $productCode: String!) {
    inventoryItems(projectId: $projectId, category: $category, productCode: $productCode) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId stockItemId
        hardwareCategory productCode quantity deficientQuantity available
        aisle row bay receivedAt createdAt updatedAt
      }
      poNumber
      classification
      unitCost
    }
  }
`;

export const GET_OPENING_ITEMS = gql`
  query GetOpeningItems($projectId: ID) {
    openingItems(projectId: $projectId) {
      id projectId openingId openingNumber
      building floor location leaf leafCount quantity
      assemblyCompletedAt state
      aisle row bay
      createdAt updatedAt
      awaitingReplacementQuantity
      neverPulledQuantity
      installedHardware {
        id openingItemId productCode hardwareCategory quantity
      }
    }
  }
`;

export const GET_OPENING_ITEM_DETAILS = gql`
  query GetOpeningItemDetails($id: ID!) {
    openingItemDetails(id: $id) {
      openingItem {
        id projectId openingId openingNumber
        building floor location leaf quantity
        assemblyCompletedAt state
        aisle row bay
        createdAt updatedAt
        installedHardware {
          id openingItemId productCode hardwareCategory quantity
        }
      }
      installedHardware {
        id openingItemId productCode hardwareCategory quantity
      }
    }
  }
`;

export const GET_OPEN_POS = gql`
  query GetOpenPOs($projectId: ID) {
    openPOs(projectId: $projectId) {
      id
      poNumber
      projectId
      status
      gpVendorId
      vendorNameSnapshot
      vendor {
        id
        name
      }
      notes
      orderedAt
      expectedDeliveryDate
      lineItems {
        id
        hardwareCategory
        productCode
        orderedQuantity
        receivedQuantity
        orderAs
      }
    }
  }
`;

export const GET_UNLOCATED_INVENTORY = gql`
  query GetUnlocatedInventory($projectId: ID) {
    unlocatedInventory(projectId: $projectId) {
      inventoryLocation {
        id projectId poLineItemId receiveLineItemId
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
 * Deliberately the complement of GET_OPEN_POS and GET_BACK_ORDERED_ITEMS, which answer "what is
 * still owed" and so drop a PO the moment it is complete. Reconciling a delivery needs the finished
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
      vendor {
        id
        name
        contactName
      }
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
  query GetPullRequests($projectId: ID, $source: PullRequestSource, $status: PullRequestStatus) {
    pullRequests(projectId: $projectId, source: $source, status: $status) {
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
      # Derived per-opening staging rollup (#343). Null on pulls that have no openings.
      stagingStatus
      stagedOpeningCount
      totalOpeningCount
      # The pick (#367). pickedAt is the moment stock left; partiallyPicked is "a short confirm is
      # outstanding" and is only computed for un-picked pulls.
      pickedAt
      pickedBy
      partiallyPicked
      items {
        id
        pullRequestId
        itemType
        openingNumber
        openingItemId
        leaf
        hardwareCategory
        productCode
        requestedQuantity
        fetchedAt
        fetchedBy
      }
    }
  }
`;

export const GET_INVENTORY_BY_VENDOR = gql`
  query GetInventoryByVendor($projectId: ID) {
    inventoryByVendor(projectId: $projectId) {
      vendorName
      totalQuantity
      totalValue
      productCodes {
        productCode
        totalQuantity
        totalValue
        # Always true here - this hierarchy is not project-scoped, so there is no single schedule to
        # compare against. Selected anyway so the field is never undefined on the client, where a
        # negated check would then flag every row in the by-vendor view.
        matchesSchedule
        items {
          id projectId poLineItemId receiveLineItemId
          hardwareCategory productCode quantity
          aisle row bay receivedAt createdAt updatedAt
        }
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
      openingItems {
        id projectId openingId warehouseId openingNumber
        building floor location leaf quantity
        assemblyCompletedAt state aisle row bay
        createdAt updatedAt
        installedHardware { id openingItemId productCode hardwareCategory quantity }
      }
      stockItems {
        id warehouseId hardwareCategory productCode quantity deficientQuantity available
        aisle row bay receivedAt createdAt updatedAt
      }
    }
  }
`;

export const GET_LOCATION_AUDIT_HISTORY = gql`
  query GetLocationAuditHistory($aisle: String!, $row: String, $bay: String, $limit: Int) {
    locationAuditHistory(aisle: $aisle, row: $row, bay: $bay, limit: $limit) {
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
      pendingPullShop
      pendingPullShipping
      backOrderedCount
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
  ) {
    stockItems(
      productCodeContains: $productCodeContains
      hardwareCategory: $hardwareCategory
      aisle: $aisle
      onlyDeficient: $onlyDeficient
      warehouseId: $warehouseId
    ) {
      id
      warehouseId
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

export const GET_STOCK_MATCHES_FOR_OPENING = gql`
  query GetStockMatchesForOpening($openingItemId: ID!) {
    stockMatchesForOpening(openingItemId: $openingItemId) {
      id
      hardwareCategory
      productCode
      quantity
      deficientQuantity
      available
      aisle
      row
      bay
    }
  }
`;

export const ADJUST_INVENTORY_QUANTITY = gql`
  mutation AdjustInventoryQuantity($inventoryLocationId: ID!, $adjustment: Int!, $reason: String!) {
    adjustInventoryQuantity(inventoryLocationId: $inventoryLocationId, adjustment: $adjustment, reason: $reason) {
      id
      projectId
      poLineItemId
      receiveLineItemId
      hardwareCategory
      productCode
      quantity
      aisle
      row
      bay
      receivedAt
      createdAt
      updatedAt
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
  reviewedBy
  reviewedAt
  rejectionReason
  # What an in-flight approval is holding the draft under, so a reviewer whose approval died
  # ambiguously can retry with the SAME key and resume rather than start a second one.
  approvalIdempotencyKey
  receiveRecordId
  outboxEntryId
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
  stagingStatus stagedOpeningCount totalOpeningCount
  pickedAt pickedBy partiallyPicked
  items {
    id pullRequestId itemType openingNumber openingItemId leaf hardwareCategory productCode requestedQuantity
    fetchedAt fetchedBy
  }
`;

// The pick screen and the printed sheet (#367). Note what is absent: any suggested quantity. The
// picker decides, and the sheet gives them received dates so they can rotate stock themselves.
const PICK_SHEET_FIELDS = `
  pullRequest { ${PULL_REQUEST_FIELDS} }
  sections {
    hardwareCategory productCode requiredQuantity appliedQuantity remainingQuantity
    claimableQuantity claimableShortfall
    leaves { openingNumber leaf quantity }
    locations {
      inventoryLocationId warehouseId warehouseCode aisle row bay
      available receivedAt draftQuantity appliedQuantity
    }
  }
  fetchItems {
    pullRequestItemId openingItemId openingNumber leaf aisle row bay state fetchedAt fetchedBy
  }
`;

// One opening of a shop-assembly pull, with the hardware lines that make up its cart (#343).
const PULL_STAGING_OPENING_FIELDS = `
  id pullRequestId openingId openingNumber leaf building floor
  pullStatus assemblyStatus assignedToUserId assignedTo stagedAt stagedBy
  items { id shopAssemblyOpeningId hardwareCategory productCode quantity allocatedQuantity }
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

export const SET_PULL_ITEM_FETCHED = gql`
  mutation SetPullItemFetched($itemId: ID!, $fetched: Boolean!) {
    setPullItemFetched(itemId: $itemId, fetched: $fetched) {
      id pullRequestId itemType openingNumber openingItemId leaf
      hardwareCategory productCode requestedQuantity fetchedAt fetchedBy
    }
  }
`;

export const COMPLETE_PULL_REQUEST = gql`
  mutation CompletePullRequest($id: ID!) {
    completePullRequest(id: $id) { ${PULL_REQUEST_FIELDS} }
  }
`;

export const GET_PULL_REQUEST_OPENINGS = gql`
  query GetPullRequestOpenings($pullRequestId: ID!) {
    pullRequestOpenings(pullRequestId: $pullRequestId) { ${PULL_STAGING_OPENING_FIELDS} }
  }
`;

export const STAGE_PULL_OPENINGS = gql`
  mutation StagePullOpenings($input: StagePullOpeningsInput!) {
    stagePullOpenings(input: $input) {
      pullRequest { ${PULL_REQUEST_FIELDS} }
      openings { ${PULL_STAGING_OPENING_FIELDS} }
      newlyStagedOpeningIds
      completed
    }
  }
`;

export const CANCEL_PULL_REQUEST = gql`
  mutation CancelPullRequest($input: CancelPullRequestInput!) {
    cancelPullRequest(input: $input) {
      pullRequest { ${PULL_REQUEST_FIELDS} }
      restocked { hardwareCategory productCode quantity }
      releasedOpeningIds
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

export const REPORT_DEFICIENCY_AT_ASSEMBLY = gql`
  mutation ReportDeficiencyAtAssembly($input: ReportDeficiencyAtAssemblyInput!) {
    reportDeficiencyAtAssembly(input: $input) {
      inventoryLocation { id quantity deficientQuantity available }
      replacementPullRequestItem {
        id pullRequestId itemType openingNumber hardwareCategory productCode requestedQuantity
      }
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
