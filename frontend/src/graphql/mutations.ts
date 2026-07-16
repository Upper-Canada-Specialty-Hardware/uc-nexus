import { gql } from '@apollo/client/core';

export const UPDATE_PO = gql`
  mutation UpdatePO($id: ID!, $vendorId: ID, $expectedDeliveryDate: Date, $preferredDeliveryDate: Date, $poNumber: String, $vendorQuoteNumber: String, $notes: String, $shippingCost: Float, $tariffAmount: Float) {
    updatePo(id: $id, vendorId: $vendorId, expectedDeliveryDate: $expectedDeliveryDate, preferredDeliveryDate: $preferredDeliveryDate, poNumber: $poNumber, vendorQuoteNumber: $vendorQuoteNumber, notes: $notes, shippingCost: $shippingCost, tariffAmount: $tariffAmount) {
      id
      poNumber
      requestNumber
      status
      gpVendorId
      vendorNameSnapshot
      vendor {
        id
        name
        contactName
        email
        phone
      }
      vendorQuoteNumber
      shippingCost
      tariffAmount
      notes
      preferredDeliveryDate
      expectedDeliveryDate
      orderedAt
      updatedAt
      lineItems {
        id
        hardwareCategory
        productCode
        classification
        orderedQuantity
        receivedQuantity
        unitCost
        orderAs
      }
      receiveRecords {
        id
        receivedAt
        receivedBy
        lineItems {
          id
          quantityReceived
        }
      }
      documents {
        id
        poId
        fileName
        contentType
        fileSize
        documentType
        uploadedAt
        downloadUrl
      }
    }
  }
`;

export const CANCEL_PO = gql`
  mutation CancelPO($id: ID!) {
    cancelPo(id: $id) {
      id
      poNumber
      requestNumber
      status
      notes
      updatedAt
      lineItems {
        id
        hardwareCategory
        productCode
        classification
        orderedQuantity
        receivedQuantity
        unitCost
        orderAs
      }
      receiveRecords {
        id
        receivedAt
        receivedBy
        lineItems {
          id
          quantityReceived
        }
      }
      documents {
        id
        poId
        fileName
        contentType
        fileSize
        documentType
        uploadedAt
        downloadUrl
      }
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
      bay
      bin
      receivedAt
      createdAt
      updatedAt
    }
  }
`;

export const OVERRIDE_INVENTORY_QUANTITY = gql`
  mutation OverrideInventoryQuantity($input: OverrideInventoryQuantityInput!) {
    overrideInventoryQuantity(input: $input) {
      id
      projectId
      poLineItemId
      receiveLineItemId
      stockItemId
      hardwareCategory
      productCode
      quantity
      deficientQuantity
      available
      aisle
      bay
      bin
      receivedAt
      createdAt
      updatedAt
    }
  }
`;

export const MOVE_INVENTORY_LOCATION = gql`
  mutation MoveInventoryLocation($inventoryLocationId: ID!, $newAisle: String!, $newBay: String!, $newBin: String!) {
    moveInventoryLocation(inventoryLocationId: $inventoryLocationId, newAisle: $newAisle, newBay: $newBay, newBin: $newBin) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle bay bin receivedAt createdAt updatedAt
    }
  }
`;

export const MARK_INVENTORY_UNLOCATED = gql`
  mutation MarkInventoryUnlocated($inventoryLocationId: ID!) {
    markInventoryUnlocated(inventoryLocationId: $inventoryLocationId) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle bay bin receivedAt createdAt updatedAt
    }
  }
`;

export const ASSIGN_INVENTORY_LOCATION = gql`
  mutation AssignInventoryLocation($inventoryLocationId: ID!, $aisle: String!, $bay: String!, $bin: String!) {
    assignInventoryLocation(inventoryLocationId: $inventoryLocationId, aisle: $aisle, bay: $bay, bin: $bin) {
      id projectId poLineItemId receiveLineItemId hardwareCategory productCode quantity aisle bay bin receivedAt createdAt updatedAt
    }
  }
`;

export const MOVE_OPENING_ITEM_LOCATION = gql`
  mutation MoveOpeningItemLocation($openingItemId: ID!, $aisle: String!, $bay: String!, $bin: String!, $warehouseId: ID) {
    moveOpeningItemLocation(openingItemId: $openingItemId, aisle: $aisle, bay: $bay, bin: $bin, warehouseId: $warehouseId) {
      id projectId openingId warehouseId openingNumber building floor location quantity assemblyCompletedAt state aisle bay bin createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const MARK_OPENING_ITEM_UNLOCATED = gql`
  mutation MarkOpeningItemUnlocated($openingItemId: ID!) {
    markOpeningItemUnlocated(openingItemId: $openingItemId) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state aisle bay bin createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const ASSIGN_OPENING_ITEM_LOCATION = gql`
  mutation AssignOpeningItemLocation($openingItemId: ID!, $aisle: String!, $bay: String!, $bin: String!) {
    assignOpeningItemLocation(openingItemId: $openingItemId, aisle: $aisle, bay: $bay, bin: $bin) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state aisle bay bin createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
    }
  }
`;

export const CREATE_RECEIVE = gql`
  mutation CreateReceive($input: CreateReceiveInput!) {
    createReceive(input: $input) {
      id
      poId
      receivedAt
      receivedBy
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
`;

export const APPROVE_PULL_REQUEST = gql`
  mutation ApprovePullRequest($id: ID!, $approvedBy: String!) {
    approvePullRequest(id: $id, approvedBy: $approvedBy) {
      pullRequest {
        id requestNumber projectId source status requestedBy assignedTo
        createdAt updatedAt approvedAt completedAt cancelledAt
        items { id pullRequestId itemType openingNumber openingItemId hardwareCategory productCode requestedQuantity }
      }
      outcome
      notification {
        id projectId recipientRole type message isRead createdAt
      }
      shortfalls {
        hardwareCategory productCode requested available short
      }
    }
  }
`;

export const COMPLETE_PULL_REQUEST = gql`
  mutation CompletePullRequest($id: ID!) {
    completePullRequest(id: $id) {
      id requestNumber projectId source status requestedBy assignedTo
      createdAt updatedAt approvedAt completedAt cancelledAt
      items { id pullRequestId itemType openingNumber openingItemId hardwareCategory productCode requestedQuantity }
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
      bay
      bin
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

export const CONFIRM_SHIPMENT = gql`
  mutation ConfirmShipment($input: ConfirmShipmentInput!) {
    confirmShipment(input: $input) {
      id
      packingSlipNumber
      projectId
      shippedBy
      shippedAt
      createdAt
      items {
        id
        packingSlipId
        itemType
        openingItemId
        openingNumber
        productCode
        hardwareCategory
        quantity
      }
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

// Register an imported Draft PO into GP (issue #175). Called only after the relay /po push succeeds:
// stamps GP's PO number + company, maps the chosen GP vendor + cost code, replaces the line items with
// the pushed set, and advances Draft -> GP-Registered.
export const REGISTER_PO_IN_GP = gql`
  mutation RegisterPoInGp($input: RegisterPOInput!) {
    registerPoInGp(input: $input) {
      id
      poNumber
      status
      gpCompany
      costCode
      gpVendorId
      vendorNameSnapshot
      vendor {
        id
        name
      }
    }
  }
`;

export const CREATE_PO = gql`
  mutation CreatePO($input: CreatePOInput!) {
    createPo(input: $input) {
      id
      poNumber
      requestNumber
      projectId
      status
      gpCompany
      gpVendorId
      vendorNameSnapshot
      vendor {
        id
        name
        contactName
        email
        phone
      }
      notes
      createdAt
      updatedAt
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
        createdAt
        updatedAt
      }
      receiveRecords {
        id
      }
      documents {
        id
      }
    }
  }
`;

export const FINALIZE_IMPORT_SESSION = gql`
  mutation FinalizeImportSession($input: FinalizeImportSessionInput!) {
    finalizeImportSession(input: $input) {
      project {
        id
        projectId
        description
        client
        jobSiteName
      }
      purchaseOrders {
        id
        poNumber
        requestNumber
        status
        notes
      }
      shippingOutPullRequests {
        id
        requestNumber
        status
      }
      shopAssemblyPullRequest {
        id
        requestNumber
        status
      }
    }
  }
`;

export const ADOPT_GP_JOB = gql`
  mutation AdoptGpJob($input: AdoptGpJobInput!) {
    adoptGpJob(input: $input) {
      id
      projectId
      description
      client
      jobSiteName
    }
  }
`;

export const UPDATE_PROJECT = gql`
  mutation UpdateProject($id: ID!, $input: UpdateProjectInput!) {
    updateProject(id: $id, input: $input) {
      id
      projectId
      description
      client
      jobSiteName
      address
      city
      state
      zip
      contractor
      projectManager
      application
      gcContactName
      gcPhone
      gcEmail
      offSiteStorageAgreement
      submittalJobNo
      submittalAssignmentCount
      estimatorCode
      titanUserId
      openingCount
      createdAt
      updatedAt
    }
  }
`;

export const UPLOAD_PO_DOCUMENT = gql`
  mutation UploadPODocument($poId: ID!, $fileName: String!, $contentType: String!, $documentType: PODocumentType!, $fileDataBase64: String!) {
    uploadPoDocument(poId: $poId, fileName: $fileName, contentType: $contentType, documentType: $documentType, fileDataBase64: $fileDataBase64) {
      id
      poId
      fileName
      contentType
      fileSize
      documentType
      uploadedAt
      downloadUrl
    }
  }
`;

export const DELETE_PO_DOCUMENT = gql`
  mutation DeletePODocument($documentId: ID!) {
    deletePoDocument(documentId: $documentId)
  }
`;

export const UPDATE_PO_LINE_ITEM_ORDER_AS = gql`
  mutation UpdatePOLineItemOrderAs($id: ID!, $orderAs: String) {
    updatePoLineItemOrderAs(id: $id, orderAs: $orderAs) {
      id
      hardwareCategory
      productCode
      classification
      orderedQuantity
      receivedQuantity
      unitCost
      orderAs
      createdAt
      updatedAt
    }
  }
`;

export const UPDATE_PO_LINE_ITEM_UNIT_COST = gql`
  mutation UpdatePOLineItemUnitCost($id: ID!, $unitCost: Float!) {
    updatePoLineItemUnitCost(id: $id, unitCost: $unitCost) {
      id
      hardwareCategory
      productCode
      classification
      orderedQuantity
      receivedQuantity
      unitCost
      orderAs
      createdAt
      updatedAt
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

export const UPDATE_USER_ROLES = gql`
  mutation UpdateUserRoles($userId: String!, $roles: [String!]!) {
    updateUserRoles(userId: $userId, roles: $roles) {
      id
      firstName
      lastName
      email
      roles
      gpBuyerId
      imageUrl
    }
  }
`;

export const UPDATE_USER_GP_BUYER_ID = gql`
  mutation UpdateUserGpBuyerId($userId: String!, $gpBuyerId: String) {
    updateUserGpBuyerId(userId: $userId, gpBuyerId: $gpBuyerId) {
      id
      firstName
      lastName
      email
      roles
      gpBuyerId
      imageUrl
    }
  }
`;

export const SAVE_BUYER_ASSIGNMENT = gql`
  mutation SaveBuyerAssignment($buyerId: String!, $projectIds: [ID!]!, $costCodes: [String!]!) {
    saveBuyerAssignment(buyerId: $buyerId, projectIds: $projectIds, costCodes: $costCodes) {
      buyerId
      costCodes
      projects {
        id
        projectId
        description
      }
    }
  }
`;

export const DELETE_BUYER_ASSIGNMENT = gql`
  mutation DeleteBuyerAssignment($buyerId: String!) {
    deleteBuyerAssignment(buyerId: $buyerId)
  }
`;

export const CREATE_VENDOR = gql`
  mutation CreateVendor($input: CreateVendorInput!) {
    createVendor(input: $input) {
      id
      name
      contactName
      email
      phone
      notes
      createdAt
      updatedAt
    }
  }
`;

export const UPDATE_VENDOR = gql`
  mutation UpdateVendor($id: ID!, $input: UpdateVendorInput!) {
    updateVendor(id: $id, input: $input) {
      id
      name
      contactName
      email
      phone
      notes
      createdAt
      updatedAt
    }
  }
`;

export const DELETE_VENDOR = gql`
  mutation DeleteVendor($id: ID!) {
    deleteVendor(id: $id)
  }
`;

const WAREHOUSE_FIELDS = `
  id
  name
  code
  address
  city
  province
  postalCode
  isPrimary
  isActive
  createdAt
  updatedAt
`;

export const CREATE_WAREHOUSE = gql`
  mutation CreateWarehouse($input: CreateWarehouseInput!) {
    createWarehouse(input: $input) {
      ${WAREHOUSE_FIELDS}
    }
  }
`;

export const UPDATE_WAREHOUSE = gql`
  mutation UpdateWarehouse($id: ID!, $input: UpdateWarehouseInput!) {
    updateWarehouse(id: $id, input: $input) {
      ${WAREHOUSE_FIELDS}
    }
  }
`;

export const DELETE_WAREHOUSE = gql`
  mutation DeleteWarehouse($id: ID!) {
    deleteWarehouse(id: $id)
  }
`;

export const SAVE_PO_DOCUMENT_DATA = gql`
  mutation SavePoDocumentData($poId: ID!, $input: SavePODocumentDataInput!) {
    savePoDocumentData(poId: $poId, input: $input) {
      id
      documentData {
        id
        poId
        vendorAddress
        buyerName
        currency
        shipTo
        shippingMethod
        proposalNumber
        freight
        miscellaneous
        taxAmount
        taxLabel
        tariffAmount
        requiredByOverride
        includeFsc
        includeUsaTariff
        includeCustoms
      }
    }
  }
`;

export const UPDATE_PO_DOCUMENT_SETTINGS = gql`
  mutation UpdatePoDocumentSettings($input: UpdatePODocumentSettingsInput!) {
    updatePoDocumentSettings(input: $input) {
      taxNumbers
      mandatoryBullets
      shippingAccounts
      shippingMethods
      customsBrokerBlock
      fscNote
      usaTariffNote
      usaTariffEffectiveUntil
      companyFromAddress
      paymentTerms
      confirmWith
      footerNotes
      signatureNote
      updatedAt
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
      aisle bay bin receivedAt
    }
  }
`;

export const ALLOCATE_STOCK_TO_PROJECT = gql`
  mutation AllocateStockToProject($input: AllocateStockToProjectInput!) {
    allocateStockToProject(input: $input) {
      id projectId hardwareCategory productCode quantity deficientQuantity available
      aisle bay bin receivedAt
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
      id aisle bay bin
    }
  }
`;

export const ASSIGN_STOCK_ITEM_LOCATION = gql`
  mutation AssignStockItemLocation($stockItemId: ID!, $aisle: String!, $bay: String!, $bin: String!) {
    assignStockItemLocation(stockItemId: $stockItemId, aisle: $aisle, bay: $bay, bin: $bin) {
      id aisle bay bin
    }
  }
`;

export const MARK_STOCK_ITEM_UNLOCATED = gql`
  mutation MarkStockItemUnlocated($stockItemId: ID!) {
    markStockItemUnlocated(stockItemId: $stockItemId) {
      id aisle bay bin
    }
  }
`;

export const MERGE_LOCATIONS = gql`
  mutation MergeLocations(
    $fromAisle: String!, $fromBay: String!, $fromBin: String!,
    $toAisle: String!, $toBay: String!, $toBin: String!
  ) {
    mergeLocations(
      fromAisle: $fromAisle, fromBay: $fromBay, fromBin: $fromBin,
      toAisle: $toAisle, toBay: $toBay, toBin: $toBin
    ) {
      inventoryLocations
      openingItems
      stockItems
    }
  }
`;

export const RECLASSIFY_STOCK_ITEM = gql`
  mutation ReclassifyStockItem($input: ReclassifyStockItemInput!) {
    reclassifyStockItem(input: $input) {
      reclassifiedStockItem {
        id hardwareCategory productCode quantity deficientQuantity available
        aisle bay bin
      }
      originalStockItem {
        id hardwareCategory productCode quantity deficientQuantity available
        aisle bay bin
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

export const PROVISION_RELAY_INSTALL = gql`
  mutation ProvisionRelayInstall($label: String!, $company: String!) {
    provisionRelayInstall(label: $label, company: $company) {
      installId
      label
      company
      enrollmentToken
      enrollmentTokenExpiresAt
    }
  }
`;
