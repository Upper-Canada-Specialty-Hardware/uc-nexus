import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_CUSTOM_INVENTORY_ITEMS, GET_INVENTORY_ITEM_TYPES } from '../graphql/customItems';

/** One thing recorded about every item of a type - "Fire Rating", "Handing" (#454). */
export interface InventoryItemAttribute {
  id: string;
  typeId: string;
  name: string;
  isActive: boolean;
  sortOrder: number;
}

/**
 * A kind of non-schedule inventory, and the attributes its items are described by (#454).
 *
 * `code` is the field that matters downstream: it is what a purchase order line writes into
 * `hardwareCategory`, so it is how stock on a shelf is recognised as belonging to this type. It is
 * fixed at creation - see the backend model for why.
 */
export interface InventoryItemType {
  id: string;
  code: string;
  name: string;
  isActive: boolean;
  sortOrder: number;
  attributes: InventoryItemAttribute[];
}

export interface CustomInventoryItemValue {
  attributeId: string;
  attributeName: string;
  value: string;
}

/** A catalogued product. `hardwareCategory` + `productCode` is the pair the pipeline carries. */
export interface CustomInventoryItem {
  id: string;
  typeId: string;
  hardwareCategory: string;
  typeName: string;
  productCode: string;
  description: string | null;
  isActive: boolean;
  values: CustomInventoryItemValue[];
}

/**
 * The item types, for anything that needs to recognise one (#454).
 *
 * Degrades to an empty list rather than blocking: every screen that calls this works perfectly well
 * without types - it just shows raw hardware categories, which is what it did before this existed.
 */
export function useInventoryItemTypes(options?: { activeOnly?: boolean; skip?: boolean }) {
  const { data, loading, refetch } = useQuery<{ inventoryItemTypes: InventoryItemType[] }>(
    GET_INVENTORY_ITEM_TYPES,
    {
      variables: { activeOnly: options?.activeOnly ?? false },
      skip: options?.skip,
      fetchPolicy: 'cache-and-network',
    },
  );
  const types = useMemo(() => data?.inventoryItemTypes ?? [], [data]);
  /** Type code -> the type, for matching a `hardwareCategory` off an inventory row. */
  const byCode = useMemo(() => new Map(types.map((t) => [t.code, t])), [types]);
  return { types, byCode, loading, refetch };
}

/**
 * The catalog, for describing stock or picking a product to order (#454).
 *
 * `byKey` is keyed on `hardwareCategory::productCode` because that pair is all an inventory row
 * carries - there is deliberately no foreign key from stock back to the catalog, so the pair is the
 * join, and it is done here rather than in a resolver so the inventory queries stay untouched.
 */
export function useCustomInventoryItems(options?: {
  typeId?: string;
  activeOnly?: boolean;
  skip?: boolean;
}) {
  const { data, loading, refetch } = useQuery<{ customInventoryItems: CustomInventoryItem[] }>(
    GET_CUSTOM_INVENTORY_ITEMS,
    {
      variables: { typeId: options?.typeId ?? null, activeOnly: options?.activeOnly ?? false },
      skip: options?.skip,
      fetchPolicy: 'cache-and-network',
    },
  );
  const items = useMemo(() => data?.customInventoryItems ?? [], [data]);
  const byKey = useMemo(
    () => new Map(items.map((i) => [`${i.hardwareCategory}::${i.productCode}`, i])),
    [items],
  );
  return { items, byKey, loading, refetch };
}

/** The key `useCustomInventoryItems().byKey` is built on. */
export function catalogKey(hardwareCategory: string, productCode: string): string {
  return `${hardwareCategory}::${productCode}`;
}
