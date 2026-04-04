import { gql } from '@apollo/client/core';

export const UPDATE_PO = gql`
  mutation UpdatePO($id: ID!, $vendorName: String, $vendorContact: String, $expectedDeliveryDate: Date, $poNumber: String, $vendorQuoteNumber: String, $notes: String) {
    updatePo(id: $id, vendorName: $vendorName, vendorContact: $vendorContact, expectedDeliveryDate: $expectedDeliveryDate, poNumber: $poNumber, vendorQuoteNumber: $vendorQuoteNumber, notes: $notes) {
      id
      poNumber
      requestNumber
      status
      vendorName
      vendorContact
      vendorQuoteNumber
      notes
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

export const MARK_PO_AS_ORDERED = gql`
  mutation MarkPOAsOrdered($id: ID!) {
    markPoAsOrdered(id: $id) {
      id
      poNumber
      requestNumber
      status
      orderedAt
      updatedAt
      vendorName
      vendorQuoteNumber
      notes
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
  mutation MoveOpeningItemLocation($openingItemId: ID!, $aisle: String!, $bay: String!, $bin: String!) {
    moveOpeningItemLocation(openingItemId: $openingItemId, aisle: $aisle, bay: $bay, bin: $bin) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state aisle bay bin createdAt updatedAt
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

export const APPROVE_SHOP_ASSEMBLY_REQUEST = gql`
  mutation ApproveShopAssemblyRequest($id: ID!) {
    approveShopAssemblyRequest(id: $id) {
      shopAssemblyRequest {
        id requestNumber projectId status createdBy approvedBy rejectedBy rejectionReason createdAt approvedAt rejectedAt
        openings {
          id shopAssemblyRequestId openingId pullStatus assignedTo assemblyStatus completedAt
          items { id shopAssemblyOpeningId hardwareCategory productCode quantity }
        }
      }
      pullRequest {
        id requestNumber projectId source status requestedBy createdAt updatedAt
        items { id pullRequestId itemType openingNumber hardwareCategory productCode requestedQuantity }
      }
    }
  }
`;

export const REJECT_SHOP_ASSEMBLY_REQUEST = gql`
  mutation RejectShopAssemblyRequest($id: ID!, $reason: String!) {
    rejectShopAssemblyRequest(id: $id, reason: $reason) {
      id requestNumber projectId status createdBy approvedBy rejectedBy rejectionReason createdAt approvedAt rejectedAt
      openings {
        id shopAssemblyRequestId openingId pullStatus assignedTo assemblyStatus completedAt
        items { id shopAssemblyOpeningId hardwareCategory productCode quantity }
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

export const CREATE_PO = gql`
  mutation CreatePO($input: CreatePOInput!) {
    createPo(input: $input) {
      id
      poNumber
      requestNumber
      projectId
      status
      vendorName
      vendorContact
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
      shopAssemblyRequest {
        id
        requestNumber
        status
      }
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
      imageUrl
    }
  }
`;

// --- Warehouse Layout mutations ---

export const CREATE_AISLE = gql`
  mutation CreateAisle($name: String!, $label: String, $orientation: String, $xPosition: Int, $yPosition: Int, $width: Int, $height: Int) {
    createAisle(name: $name, label: $label, orientation: $orientation, xPosition: $xPosition, yPosition: $yPosition, width: $width, height: $height) {
      id name label orientation xPosition yPosition width height isActive
      rows { id aisleId name level isActive }
      bays { id name bins { id name } }
    }
  }
`;

export const UPDATE_AISLE = gql`
  mutation UpdateAisle($id: ID!, $name: String, $label: String, $orientation: String, $xPosition: Int, $yPosition: Int, $width: Int, $height: Int, $isActive: Boolean) {
    updateAisle(id: $id, name: $name, label: $label, orientation: $orientation, xPosition: $xPosition, yPosition: $yPosition, width: $width, height: $height, isActive: $isActive) {
      id name label orientation xPosition yPosition width height isActive
      rows { id aisleId name level isActive }
      bays { id name bins { id name } }
    }
  }
`;

export const CREATE_ROW = gql`
  mutation CreateRow($aisleId: ID!, $name: String!, $level: Int) {
    createRow(aisleId: $aisleId, name: $name, level: $level) {
      id aisleId name level isActive
    }
  }
`;

export const UPDATE_ROW = gql`
  mutation UpdateRow($id: ID!, $name: String, $level: Int, $isActive: Boolean) {
    updateRow(id: $id, name: $name, level: $level, isActive: $isActive) {
      id aisleId name level isActive
    }
  }
`;

export const CREATE_BAY = gql`
  mutation CreateBay($aisleId: ID!, $name: String!, $rowPosition: Int, $colPosition: Int) {
    createBay(aisleId: $aisleId, name: $name, rowPosition: $rowPosition, colPosition: $colPosition) {
      id aisleId name rowPosition colPosition isActive bins { id name }
    }
  }
`;

export const UPDATE_BAY = gql`
  mutation UpdateBay($id: ID!, $name: String, $rowPosition: Int, $colPosition: Int, $isActive: Boolean) {
    updateBay(id: $id, name: $name, rowPosition: $rowPosition, colPosition: $colPosition, isActive: $isActive) {
      id aisleId name rowPosition colPosition isActive bins { id name }
    }
  }
`;

export const CREATE_BIN = gql`
  mutation CreateBin($bayId: ID!, $name: String!, $rowId: ID, $rowPosition: Int, $colPosition: Int, $capacity: Int) {
    createBin(bayId: $bayId, name: $name, rowId: $rowId, rowPosition: $rowPosition, colPosition: $colPosition, capacity: $capacity) {
      id bayId rowId name rowPosition colPosition capacity isActive
    }
  }
`;

export const UPDATE_BIN = gql`
  mutation UpdateBin($id: ID!, $name: String, $rowPosition: Int, $colPosition: Int, $capacity: Int, $isActive: Boolean) {
    updateBin(id: $id, name: $name, rowPosition: $rowPosition, colPosition: $colPosition, capacity: $capacity, isActive: $isActive) {
      id bayId rowId name rowPosition colPosition capacity isActive
    }
  }
`;

export const CLONE_AISLE = gql`
  mutation CloneAisle($aisleId: ID!, $newName: String!, $xPosition: Int, $yPosition: Int) {
    cloneAisle(aisleId: $aisleId, newName: $newName, xPosition: $xPosition, yPosition: $yPosition) {
      id name label orientation xPosition yPosition width height isActive
      rows { id aisleId name level isActive }
      bays { id name bins { id name } }
    }
  }
`;
