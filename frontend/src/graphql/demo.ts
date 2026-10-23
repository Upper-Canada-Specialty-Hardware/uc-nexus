import { gql } from '@apollo/client/core';

// #1608: demo mode. Turning it on builds the demo the first time anybody does, and only an account of a
// UBC company may (#1658); turning it off is open to anybody in it.
export const SET_MY_DEMO_MODE = gql`
  mutation SetMyDemoMode($enabled: Boolean!) {
    setMyDemoMode(enabled: $enabled) {
      id
      demoMode
    }
  }
`;

// #1697: anybody in demo mode resets the demo, and everybody else is told. The status read is answered
// while a reset runs - every other demo read is refused then - so a tab can wait one out.
const DEMO_RESET_STATUS_FIELDS = `
  building
  buildStartedAt
  buildStartedBy
  notice { resetAt resetBy }
  failure { failedAt startedBy }
`;

export const GET_DEMO_RESET_STATUS = gql`
  query GetDemoResetStatus {
    demoResetStatus { ${DEMO_RESET_STATUS_FIELDS} }
  }
`;

export const RESET_DEMO = gql`
  mutation ResetDemo {
    resetDemo { ${DEMO_RESET_STATUS_FIELDS} }
  }
`;

export const ACKNOWLEDGE_DEMO_RESET = gql`
  mutation AcknowledgeDemoReset {
    acknowledgeDemoReset { ${DEMO_RESET_STATUS_FIELDS} }
  }
`;
