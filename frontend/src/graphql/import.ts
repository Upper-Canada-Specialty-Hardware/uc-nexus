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
      }
      hardwareItems {
        openingNumber
        productCode
        materialId
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

export const GET_GP_JOBS = gql`
  query GetGpJobs($company: String!) {
    gpJobs(company: $company) {
      jobNumber
      jobName
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
