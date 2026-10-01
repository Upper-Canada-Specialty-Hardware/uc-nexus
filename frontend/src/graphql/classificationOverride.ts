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
      note
    }
  }
`;

// #1050: what saving these changes would do, product by product. Writes nothing.
export const GET_HARDWARE_CLASSIFICATION_IMPACT = gql`
  query GetHardwareClassificationImpact($input: SetHardwareClassificationsInput!) {
    hardwareClassificationImpact(input: $input) {
      hardwareCategory
      productCode
      fromChoice
      toChoice
      wentOut
      adjusts
      unaffected
      blocks
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
