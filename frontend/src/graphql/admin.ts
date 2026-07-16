import { gql } from '@apollo/client/core';

export const GET_ADMIN_PROJECTS = gql`
  query GetAdminProjects {
    adminProjects {
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

export const GET_OPENING_HARDWARE_STATUS = gql`
  query GetOpeningHardwareStatus($projectId: ID) {
    openingHardwareStatus(projectId: $projectId) {
      openingNumber
      building
      floor
      location
      items {
        hardwareCategory
        productCode
        itemQuantity
        status
      }
    }
  }
`;

export const GET_USERS = gql`
  query GetUsers {
    users {
      id
      firstName
      lastName
      email
      roles
      imageUrl
    }
  }
`;

export const RELAY_INSTALLS = gql`
  query RelayInstalls {
    relayInstalls {
      id
      label
      company
      hostname
      enrolled
      enrolledAt
      lastSeenAt
      createdAt
    }
  }
`;

export const GET_LOCATION_DUPLICATES = gql`
  query GetLocationDuplicates {
    locationDuplicates {
      canonicalAisle
      canonicalBay
      canonicalBin
      variants { aisle bay bin }
    }
  }
`;

export const GET_PROJECT_PROGRESS_BY_PRODUCT = gql`
  query GetProjectProgressByProduct($projectId: ID!) {
    projectProgressByProduct(projectId: $projectId) {
      hardwareCategory
      productCode
      requiredQuantity
      poDrafted
      orderedQuantity
      receivedQuantity
      backOrdered
      shippedOut
    }
  }
`;

export const GET_ADMIN_STATS = gql`
  query GetAdminStats {
    adminStats {
      vendorCount
      userCount
      hardwareItemCount
      openingCount
    }
  }
`;

// ---------------------------------------------------------------------------
// Stock pool + deficiency
// ---------------------------------------------------------------------------

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

export const ASSIGN_OPENING_ITEM_LOCATION = gql`
  mutation AssignOpeningItemLocation($openingItemId: ID!, $aisle: String!, $bay: String!, $bin: String!) {
    assignOpeningItemLocation(openingItemId: $openingItemId, aisle: $aisle, bay: $bay, bin: $bin) {
      id projectId openingId openingNumber building floor location quantity assemblyCompletedAt state aisle bay bin createdAt updatedAt
      installedHardware { id openingItemId productCode hardwareCategory quantity }
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
