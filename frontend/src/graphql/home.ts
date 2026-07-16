import { gql } from '@apollo/client/core';

export const GET_HOME_DASHBOARD_STATS = gql`
  query GetHomeDashboardStats {
    homeDashboardStats {
      openPoCount
      pendingPullRequestCount
      itemsPendingReceiving
      projectCount
    }
  }
`;
