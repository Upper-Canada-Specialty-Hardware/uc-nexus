import { gql } from '@apollo/client/core';

export const GET_PO_STATISTICS = gql`
  query GetPOStatistics($projectId: ID) {
    poStatistics(projectId: $projectId) {
      total
      draft
      gpRegistered
      vendorConfirmed
      partiallyReceived
      closed
    }
  }
`;

// Presigned S3 URL for a single PO document (packing slip, vendor ack, etc.), minted on demand so the
// link is never stale. Auth-gated server-side (#415). Used to view a receive's packing slip without
// carrying the whole document collection on every draft row.
export const GET_PO_DOCUMENT_DOWNLOAD_URL = gql`
  query PoDocumentDownloadUrl($documentId: ID!) {
    poDocumentDownloadUrl(documentId: $documentId)
  }
`;

export const GET_PURCHASE_ORDERS = gql`
  query GetPurchaseOrders($projectId: ID, $status: POStatus) {
    purchaseOrders(projectId: $projectId, status: $status) {
      id
      poNumber
      requestNumber
      projectId
      status
      gpCompany
      gpVendorId
      vendorNameSnapshot
      buyerId
      vendorQuoteNumber
      # #490's register-dialog seed reads registerPo.costCode off this row; without the field the
      # draft's code never reaches the dialog and the buyer is asked to pick it a second time.
      costCode
      shippingCost
      tariffAmount
      notes
      preferredDeliveryDate
      expectedDeliveryDate
      orderedAt
      createdAt
      updatedAt
      documentData {
        id
        poId
        vendorAddress
        buyerName
        currency
        shipTo
        shippingMethod
        quotationNumber
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
        manufacturer
        createdAt
        updatedAt
      }
      receiveRecords {
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

// One PO with the full detail the PO modal renders (gp-owned-po mirror). The register list is slim
// (purchaseOrdersPage), so opening a row fetches its lines/documents/receives here on demand.
export const GET_PURCHASE_ORDER = gql`
  query GetPurchaseOrder($id: ID!) {
    purchaseOrder(id: $id) {
      id
      poNumber
      requestNumber
      origin
      gpSyncedAt
      projectId
      status
      gpCompany
      gpVendorId
      vendorNameSnapshot
      buyerId
      vendorQuoteNumber
      costCode
      shippingCost
      tariffAmount
      notes
      preferredDeliveryDate
      expectedDeliveryDate
      orderedAt
      createdAt
      updatedAt
      documentData {
        id
        poId
        vendorAddress
        buyerName
        currency
        shipTo
        shippingMethod
        quotationNumber
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
        manufacturer
        createdAt
        updatedAt
      }
      receiveRecords {
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

// The company-scale register (gp-owned-po mirror): server-driven paging/search/sort. Rows are slim -
// a lineItemCount scalar instead of the line collection - so the list never materializes every line of
// every PO. Opening a row loads the full PO via GET_PURCHASE_ORDER.
export const PURCHASE_ORDERS_PAGE = gql`
  query PurchaseOrdersPage(
    $search: String
    $statuses: [POStatus!]
    $origin: POOrigin
    $projectId: ID
    $sortField: String
    $sortDir: String
    $limit: Int
    $offset: Int
  ) {
    purchaseOrdersPage(
      search: $search
      statuses: $statuses
      origin: $origin
      projectId: $projectId
      sortField: $sortField
      sortDir: $sortDir
      limit: $limit
      offset: $offset
    ) {
      totalCount
      rows {
        id
        poNumber
        requestNumber
        projectId
        status
        origin
        gpCompany
        vendorNameSnapshot
        orderedAt
        expectedDeliveryDate
        createdAt
        gpSyncedAt
        lineItemCount
      }
    }
  }
`;

// Admin: run one GP PO mirror pass now (gp-owned-po mirror).
export const SYNC_GP_POS = gql`
  mutation SyncGpPos {
    syncGpPos {
      mode
      created
      updated
      backfillDone
    }
  }
`;

// Attach project schedule hardware to a mirrored PO's lines for coverage tracking (gp-owned-po mirror).
export const LINK_SCHEDULE_TO_MIRRORED_PO = gql`
  mutation LinkScheduleToMirroredPo($input: LinkScheduleToMirroredPoInput!) {
    linkScheduleToMirroredPo(input: $input) {
      id
      lineItems {
        id
        hardwareCategory
        productCode
        orderedQuantity
        receivedQuantity
      }
    }
  }
`;

// Issue #232: suggest a GP ordering vendor for a hardware line's TITAN manufacturer. A saved mapping
// wins (savedMapping true, one candidate at score 100); otherwise the top-N live vendors ranked by
// fuzzy score are returned (savedMapping false).
export const SUGGEST_VENDOR_FOR_MANUFACTURER = gql`
  query SuggestVendorForManufacturer($gpCompany: String!, $manufacturer: String!) {
    suggestVendorForManufacturer(gpCompany: $gpCompany, manufacturer: $manufacturer) {
      manufacturer
      savedMapping
      candidates {
        gpVendorId
        gpVendorName
        score
      }
    }
  }
`;

export const GET_GP_BUYERS = gql`
  query GetGpBuyers($company: String!) {
    gpBuyers(company: $company)
  }
`;

export const GET_GP_PO_TOTALS = gql`
  query GetGpPoTotals($company: String!, $poNumber: String!) {
    gpPoTotals(company: $company, poNumber: $poNumber) {
      poNumber
      subtotal
      freight
      miscellaneous
      taxAmount
    }
  }
`;

export const GET_GP_COST_CODES = gql`
  query GetGpCostCodes($company: String!, $job: String!) {
    gpCostCodes(company: $company, job: $job) {
      costCode
      description
      costElement
    }
  }
`;

export const GET_GP_VENDORS = gql`
  query GetGpVendors($company: String!) {
    gpVendors(company: $company) {
      vendorId
      vendorName
      vendorClass
      status
      currency
    }
  }
`;

// Issue #257: GP purchase tax details (TX00201, TXDTLTYP=2) for the register-PO tax-detail dropdown.
export const GET_GP_TAX_DETAILS = gql`
  query GetGpTaxDetails($company: String!) {
    gpTaxDetails(company: $company) {
      taxDetailId
      description
      percent
    }
  }
`;

export const PO_DOCUMENT_SETTINGS_FIELDS = `
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
`;

export const GET_PO_DOCUMENT_SETTINGS = gql`
  query GetPoDocumentSettings {
    poDocumentSettings {
      ${PO_DOCUMENT_SETTINGS_FIELDS}
    }
  }
`;

export const GET_PROJECT_SHIP_TO = gql`
  query GetProjectShipTo($projectId: ID!) {
    projectShipTo(projectId: $projectId) {
      id
      projectId
      jobSiteName
      address
      city
      state
      zip
    }
  }
`;

export const UPDATE_PO = gql`
  mutation UpdatePO($id: ID!, $expectedDeliveryDate: Date, $preferredDeliveryDate: Date, $poNumber: String, $vendorQuoteNumber: String, $notes: String, $shippingCost: Float, $tariffAmount: Float) {
    updatePo(id: $id, expectedDeliveryDate: $expectedDeliveryDate, preferredDeliveryDate: $preferredDeliveryDate, poNumber: $poNumber, vendorQuoteNumber: $vendorQuoteNumber, notes: $notes, shippingCost: $shippingCost, tariffAmount: $tariffAmount) {
      id
      poNumber
      requestNumber
      status
      gpVendorId
      vendorNameSnapshot
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

// Register an imported Draft PO into GP (issue #175). Called only after the relay /po push succeeds:
// stamps GP's PO number + company, maps the chosen GP vendor + cost code, replaces the line items with
// the pushed set, and advances Draft -> GP-Registered.
// #353 PR E: the result is now a wrapper. `queued` true means the GP relay was unreachable and the
// registration is on the durable outbox - the PO comes back still DRAFT and advances itself when the
// queue drains, so the caller must not treat it as registered.
export const REGISTER_PO_IN_GP = gql`
  mutation RegisterPoInGp($input: RegisterPOInput!) {
    registerPoInGp(input: $input) {
      queued
      outboxEntryId
      purchaseOrder {
        id
        poNumber
        status
        gpCompany
        costCode
        gpVendorId
        vendorNameSnapshot
      }
    }
  }
`;

export const CREATE_DRAFT_PO = gql`
  mutation CreateDraftPO($input: CreateDraftPOInput!) {
    createDraftPo(input: $input) {
      id
      poNumber
      requestNumber
      projectId
      status
      gpCompany
      gpVendorId
      vendorNameSnapshot
      costCode
      vendorQuoteNumber
      notes
      preferredDeliveryDate
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
        quotationNumber
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

// #500: send the generated supplier PO to the vendor it was placed with. The vendor's email is read
// live from GP through the relay - Nexus stores no vendor contact (#509), so it cannot go stale.
// Every refusal comes back as sent:false with a message the user can act on, not an error.
export const EMAIL_PO_TO_VENDOR = gql`
  mutation EmailPoToVendor($poId: ID!) {
    emailPoToVendor(poId: $poId) {
      sent
      message
      sentTo
    }
  }
`;
