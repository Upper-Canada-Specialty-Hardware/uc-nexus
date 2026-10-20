import { gql } from '@apollo/client/core';

// INVENTORY VALUE (#662). Every mutation on the page returns the WHOLE page, not the row it changed:
// each edit moves one of the three figures, so a mutation answering with just its row would leave
// the screen showing totals that no longer follow from the table under them. One shared selection
// keeps the four documents normalizing into the same cache entry. usdHardwareValue (#1557) is the
// hardware bought on USD POs, in US dollars, shown beside each figure rather than in it.
export const INVENTORY_VALUE_FIELDS = `
  company
  ossa { hardwareValue doorCount doorValue totalValue usdHardwareValue }
  nonOssa { hardwareValue doorCount doorValue totalValue usdHardwareValue }
  generalStock { hardwareValue doorCount doorValue totalValue usdHardwareValue }
  overhead { hardwareValue doorCount doorValue totalValue usdHardwareValue }
  averageDoorCost
  averageDoorCostUpdatedAt
  averageDoorCostUpdatedBy
  doorsOnHand {
    id
    projectId
    projectNumber
    projectName
    isOssa
    quantity
  }
  generalDoorCount
  ossaDoorCount
  nonOssaDoorCount
  totalDoorCount
`;

export const GET_INVENTORY_VALUE = gql`
  query GetInventoryValue($company: String!) {
    inventoryValue(company: $company) {
      ${INVENTORY_VALUE_FIELDS}
    }
  }
`;

export const SAVE_DOORS_ON_HAND = gql`
  mutation SaveDoorsOnHand($input: SaveDoorsOnHandInput!) {
    saveDoorsOnHand(input: $input) {
      ${INVENTORY_VALUE_FIELDS}
    }
  }
`;

export const REMOVE_DOORS_ON_HAND = gql`
  mutation RemoveDoorsOnHand($id: ID!) {
    removeDoorsOnHand(id: $id) {
      ${INVENTORY_VALUE_FIELDS}
    }
  }
`;

export const SET_AVERAGE_DOOR_COST = gql`
  mutation SetAverageDoorCost($company: String!, $amount: Float!) {
    setAverageDoorCost(company: $company, amount: $amount) {
      ${INVENTORY_VALUE_FIELDS}
    }
  }
`;
