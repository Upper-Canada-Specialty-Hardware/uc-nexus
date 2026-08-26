import type { WarehouseLocationDef } from './receiveDraftTypes';

export interface LocationEntry {
  warehouseId: string | null;
  aisle: string;
  row: string | null;
  bay: string | null;
  itemCount: number;
  totalQuantity: number;
}

/** #632: registry linkage. definedId null on an occupied location that is NOT defined (a
 *  pre-registry variant); active null likewise. isEmpty marks a defined location holding nothing. */
export type CombinedLocationRow = LocationEntry & {
  definedId: string | null;
  active: boolean | null;
  isEmpty: boolean;
};

/** A stable key for one rack position, shared between the utilization list and the product rows. */
export function locationKey(
  warehouseId: string | null,
  aisle: string | null,
  row: string | null,
  bay: string | null,
): string {
  return `${warehouseId ?? 'none'}|${aisle ?? ''}|${row ?? ''}|${bay ?? ''}`;
}

/**
 * Occupied locations first (linked to their registry row when one matches), then every defined
 * location holding nothing - the #632 point: a freshly defined bin exists before anything is in it,
 * and the derived-from-occupancy list simply could not show it.
 *
 * This is the full list the Locations page is about, so the header counter counts from here rather
 * than from utilization alone (#634).
 */
export function combineLocationRows(
  occupied: LocationEntry[],
  registry: WarehouseLocationDef[],
): CombinedLocationRow[] {
  const registryByKey = new Map<string, WarehouseLocationDef>();
  for (const def of registry) {
    registryByKey.set(locationKey(def.warehouseId, def.aisle, def.row, def.bay), def);
  }

  const occupiedKeys = new Set(
    occupied.map((loc) => locationKey(loc.warehouseId, loc.aisle, loc.row, loc.bay)),
  );
  const combined: CombinedLocationRow[] = occupied.map((loc) => {
    const def = registryByKey.get(locationKey(loc.warehouseId, loc.aisle, loc.row, loc.bay));
    return { ...loc, definedId: def?.id ?? null, active: def?.active ?? null, isEmpty: false };
  });
  for (const def of registry) {
    if (occupiedKeys.has(locationKey(def.warehouseId, def.aisle, def.row, def.bay))) continue;
    combined.push({
      warehouseId: def.warehouseId,
      aisle: def.aisle,
      row: def.row,
      bay: def.bay,
      itemCount: 0,
      totalQuantity: 0,
      definedId: def.id,
      active: def.active ?? null,
      isEmpty: true,
    });
  }
  return combined;
}
