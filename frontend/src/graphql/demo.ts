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
