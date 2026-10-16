import { gql } from '@apollo/client/core';

// #1677: the report bubble. Files the report as a GitHub issue and emails the product owner; who sent
// it comes from the session, so the input carries only what the browser knows.
export const SUBMIT_ISSUE_REPORT = gql`
  mutation SubmitIssueReport($input: SubmitIssueReportInput!) {
    submitIssueReport(input: $input) {
      issueNumber
      issueUrl
      emailed
    }
  }
`;
