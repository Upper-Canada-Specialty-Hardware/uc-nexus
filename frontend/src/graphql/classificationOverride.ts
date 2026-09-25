import { gql } from '@apollo/client/core';

// #735: the Tenant Owner's override of a project's hardware classifications after import.

export const GET_PROJECT_HARDWARE_CLASSIFICATIONS = gql`
  query GetProjectHardwareClassifications($projectId: ID!) {
    projectHardwareClassifications(projectId: $projectId) {
      hardwareCategory
      productCode
      quantity
      openingCount
      choice
    }
  }
`;

export const GET_HARDWARE_CLASSIFICATION_CHANGES = gql`
  query GetHardwareClassificationChanges($projectId: ID!) {
    hardwareClassificationChanges(projectId: $projectId) {
      id
      hardwareCategory
      productCode
      fromChoice
      toChoice
      changedBy
      changedAt
    }
  }
`;

export const SET_HARDWARE_CLASSIFICATIONS = gql`
  mutation SetHardwareClassifications($input: SetHardwareClassificationsInput!) {
    setHardwareClassifications(input: $input) {
      hardwareCategory
      productCode
      quantity
      openingCount
      choice
    }
  }
`;
