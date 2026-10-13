import { gql } from '@apollo/client/core';

// #1608: demo mode. Turning it on seeds the demo company the first time anybody does; turning it off
// is open to anybody in it.
export const SET_MY_DEMO_MODE = gql`
  mutation SetMyDemoMode($enabled: Boolean!) {
    setMyDemoMode(enabled: $enabled) {
      id
      demoMode
    }
  }
`;

// Wipes the demo company and seeds it again. Only from inside demo mode.
export const RESET_DEMO_DATA = gql`
  mutation ResetDemoData {
    resetDemoData
  }
`;
