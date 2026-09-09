import { gql } from '@apollo/client/core';

// INVENTORY VALUE (#662). Every mutation on the page returns the WHOLE page, not the row it changed:
// each edit moves one of the three figures, so a mutation answering with just its row would leave
// the screen showing totals that no longer follow from the table under them. One shared selection
// keeps the four documents normalizing into the same cache entry.
export const INVENTORY_VALUE_FIELDS = `
  company
  ossa { hardwareValue doorCount doorValue totalValue }
  nonOssa { hardwareValue doorCount doorValue totalValue }
  generalStock { hardwareValue doorCount doorValue totalValue }
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

// Read off Nexus's own projects rather than the relay's company list, so the page still opens when
// the relay is down. A scoped user gets exactly one entry.
export const GET_INVENTORY_VALUE_COMPANIES = gql`
  query GetInventoryValueCompanies {
    inventoryValueCompanies
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
