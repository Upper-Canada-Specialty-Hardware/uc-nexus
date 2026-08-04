import { gql } from '@apollo/client/core';

// The catalog of non-schedule inventory - frames, specialties, consumables (#454).
//
// Three screens read this: the management page that maintains it, the Create PO dialog's picker, and
// the inventory views that use it to describe what is on a shelf. `hardwareCategory` on an item is
// its type's code, spelled the way every pipeline row spells it - which is how the inventory screens
// match a catalog entry to stock without knowing the catalog's shape.

const ATTRIBUTE_FIELDS = gql`
  fragment AttributeFields on InventoryItemAttribute {
    id
    typeId
    name
    isActive
    sortOrder
  }
`;

export const GET_INVENTORY_ITEM_TYPES = gql`
  ${ATTRIBUTE_FIELDS}
  query GetInventoryItemTypes($activeOnly: Boolean) {
    inventoryItemTypes(activeOnly: $activeOnly) {
      id
      code
      name
      isActive
      sortOrder
      attributes {
        ...AttributeFields
      }
    }
  }
`;

export const GET_CUSTOM_INVENTORY_ITEMS = gql`
  query GetCustomInventoryItems($typeId: ID, $productCodeContains: String, $activeOnly: Boolean) {
    customInventoryItems(
      typeId: $typeId
      productCodeContains: $productCodeContains
      activeOnly: $activeOnly
    ) {
      id
      typeId
      hardwareCategory
      typeName
      productCode
      description
      isActive
      values {
        attributeId
        attributeName
        value
      }
    }
  }
`;

export const CREATE_INVENTORY_ITEM_TYPE = gql`
  ${ATTRIBUTE_FIELDS}
  mutation CreateInventoryItemType($name: String!, $code: String, $sortOrder: Int) {
    createInventoryItemType(name: $name, code: $code, sortOrder: $sortOrder) {
      id
      code
      name
      isActive
      sortOrder
      attributes {
        ...AttributeFields
      }
    }
  }
`;

export const UPDATE_INVENTORY_ITEM_TYPE = gql`
  ${ATTRIBUTE_FIELDS}
  mutation UpdateInventoryItemType($id: ID!, $name: String, $isActive: Boolean, $sortOrder: Int) {
    updateInventoryItemType(id: $id, name: $name, isActive: $isActive, sortOrder: $sortOrder) {
      id
      code
      name
      isActive
      sortOrder
      attributes {
        ...AttributeFields
      }
    }
  }
`;

// Both attribute mutations return the whole type: the caller re-renders its entire column set from
// one round trip rather than splicing an attribute into a list it holds separately.
export const CREATE_INVENTORY_ITEM_ATTRIBUTE = gql`
  ${ATTRIBUTE_FIELDS}
  mutation CreateInventoryItemAttribute($typeId: ID!, $name: String!, $sortOrder: Int) {
    createInventoryItemAttribute(typeId: $typeId, name: $name, sortOrder: $sortOrder) {
      id
      code
      name
      isActive
      sortOrder
      attributes {
        ...AttributeFields
      }
    }
  }
`;

export const UPDATE_INVENTORY_ITEM_ATTRIBUTE = gql`
  ${ATTRIBUTE_FIELDS}
  mutation UpdateInventoryItemAttribute($id: ID!, $name: String, $isActive: Boolean, $sortOrder: Int) {
    updateInventoryItemAttribute(id: $id, name: $name, isActive: $isActive, sortOrder: $sortOrder) {
      id
      code
      name
      isActive
      sortOrder
      attributes {
        ...AttributeFields
      }
    }
  }
`;

export const CREATE_CUSTOM_INVENTORY_ITEM = gql`
  mutation CreateCustomInventoryItem(
    $typeId: ID!
    $productCode: String!
    $description: String
    $values: [CustomInventoryItemValueInput!]
  ) {
    createCustomInventoryItem(
      typeId: $typeId
      productCode: $productCode
      description: $description
      values: $values
    ) {
      id
      typeId
      hardwareCategory
      typeName
      productCode
      description
      isActive
      values {
        attributeId
        attributeName
        value
      }
    }
  }
`;

export const UPDATE_CUSTOM_INVENTORY_ITEM = gql`
  mutation UpdateCustomInventoryItem(
    $id: ID!
    $description: String
    $isActive: Boolean
    $values: [CustomInventoryItemValueInput!]
  ) {
    updateCustomInventoryItem(id: $id, description: $description, isActive: $isActive, values: $values) {
      id
      typeId
      hardwareCategory
      typeName
      productCode
      description
      isActive
      values {
        attributeId
        attributeName
        value
      }
    }
  }
`;
