import { gql } from '@apollo/client/core';

export const GET_PROJECT_HARDWARE_SCHEDULE = gql`
  query GetProjectHardwareSchedule($projectId: ID!) {
    projectHardwareSchedule(projectId: $projectId) {
      project {
        projectId
        description
        jobSiteName
        address
        city
        state
        zip
        contractor
        projectManager
        application
        submittalJobNo
        submittalAssignmentCount
        estimatorCode
        titanUserId
      }
      openings {
        openingNumber
        building
        floor
        location
        locationTo
        locationFrom
        hand
        width
        length
        doorThickness
        jambThickness
        doorType
        frameType
        interiorExterior
        keying
        headingNo
        singlePair
        assignmentMultiplier
        leafCount
      }
      hardwareItems {
        openingNumber
        productCode
        materialId
        leaf
        hardwareCategory
        itemQuantity
        unitCost
        unitPrice
        listPrice
        vendorDiscount
        markupPct
        vendorNo
        manufacturer
        phaseCode
        itemCategoryCode
        productGroupCode
        submittalId
      }
    }
  }
`;

export const GET_PROJECT_BY_SCHEDULE_ID = gql`
  query GetProjectByScheduleId($projectId: String!) {
    projectByScheduleId(projectId: $projectId) {
      id
      projectId
      description
      jobSiteName
    }
  }
`;

export const GET_PROJECT_EXCLUDED_ITEMS = gql`
  query GetProjectExcludedItems($projectId: ID!) {
    projectExcludedItems(projectId: $projectId) {
      hardwareCategory
      productCode
    }
  }
`;

export const RECONCILE_SCHEDULE = gql`
  query ReconcileSchedule($projectId: ID!, $items: [ReconciliationItemInput!]!) {
    reconcileSchedule(projectId: $projectId, items: $items) {
      openingNumber
      hardwareCategory
      productCode
      quantity
      status
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
      shippingOutRequests {
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

// Issue #380: the create-job form's live GP reads. Nexus stores none of this - customer, address
// codes, tax schedule and division all come from GP, which is why the form cannot be composed while
// the relay is down.
export const GET_GP_CUSTOMERS = gql`
  query GetGpCustomers($company: String!) {
    gpCustomers(company: $company) {
      customerNumber
      customerName
    }
  }
`;

export const GET_GP_CUSTOMER_ADDRESSES = gql`
  query GetGpCustomerAddresses($company: String!, $customer: String!) {
    gpCustomerAddresses(company: $company, customer: $customer) {
      addressCode
      address1
      city
      state
    }
  }
`;

export const GET_GP_TAX_SCHEDULES = gql`
  query GetGpTaxSchedules($company: String!) {
    gpTaxSchedules(company: $company) {
      taxScheduleId
      description
    }
  }
`;

export const GET_GP_DIVISIONS = gql`
  query GetGpDivisions($company: String!) {
    gpDivisions(company: $company)
  }
`;

export const CREATE_GP_JOB = gql`
  mutation CreateGpJob($input: CreateGpJobInput!) {
    createGpJob(input: $input) {
      id
      projectId
      description
      client
      jobSiteName
    }
  }
`;
