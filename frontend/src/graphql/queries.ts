import { gql } from '@apollo/client/core';

export const GET_PROJECTS = gql`
  query GetProjects {
    projects {
      id
      projectId
      description
      jobSiteName
    }
  }
`;
