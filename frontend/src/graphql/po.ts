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
      cancelled
    }
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
        vendor {
          id
          name
        }
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
      vendor {
        id
        name
        contactName
        email
        phone
      }
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

// Which door openings and leaves this PO's hardware was bought for (#302). Read only by the PO detail
// modal - the PO list must never pay for this join.
export const GET_PO_OPENINGS = gql`
  query GetPoOpenings($poId: ID!) {
    poOpenings(poId: $poId) {
      openingNumber
      leaf
      building
      floor
      location
      items {
        hardwareCategory
        productCode
        quantity
      }
    }
  }
`;
