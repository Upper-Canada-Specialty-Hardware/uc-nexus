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

// Issue #444: an address the job needs but GP does not hold yet. No company argument - the backend
// uses the connected relay's own company, the same one the reads above are keyed on. The selected
// fields deliberately mirror gpCustomerAddresses above: the dialog writes the returned row straight
// into that query's cache entry, which is what lets the picker offer the new code immediately rather
// than only once a re-read of GP has landed.
export const CREATE_GP_CUSTOMER_ADDRESS = gql`
  mutation CreateGpCustomerAddress($input: CreateGpCustomerAddressInput!) {
    createGpCustomerAddress(input: $input) {
      addressCode
      address1
      city
      state
    }
  }
`;

// Issue #392: the job proc validates Estimator/WS Manager against the payroll master, so they are
// pickers, not free text.
export const GET_GP_EMPLOYEES = gql`
  query GetGpEmployees($company: String!) {
    gpEmployees(company: $company) {
      employeeId
      firstName
      lastName
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

// Issue #392: `created` distinguishes GP actually creating the job from the mutation adopting one GP
// already held, so the toast can stop claiming a creation that did not happen.
export const CREATE_GP_JOB = gql`
  mutation CreateGpJob($input: CreateGpJobInput!) {
    createGpJob(input: $input) {
      created
      # id only: the dialog reads created, and the list is refreshed by refetchQueries, so the rest
      # of the project would be fetched and thrown away.
      project {
        id
      }
    }
  }
`;
