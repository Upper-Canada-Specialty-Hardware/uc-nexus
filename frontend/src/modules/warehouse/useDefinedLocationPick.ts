import { useMemo } from 'react';
import { useQuery } from '@apollo/client/react';
import { GET_WAREHOUSE_LOCATIONS } from '../../graphql/warehouse';
import { type WarehouseLocationDef, normalizeLocationValue } from './receiveDraftTypes';

export interface DefinedLocationPick {
  aisleOptions: string[];
  rowOptions: string[];
  bayOptions: string[];
  /** The aisle / row / bay triple matches a defined, active location exactly. */
  isDefinedPick: boolean;
  /** #1345: the registry has loaded and defines no location in the given warehouse(s), so no pick
   *  can ever validate - the caller says so instead of "pick a defined aisle". */
  registryEmpty: boolean;
}

/**
 * The strict, cascading defined-location picks put away makes (#632), shared by every dialog that
 * lands hardware on a bin (#975, #1046). A location is offered when it is defined in every given
 * warehouse - each item lands within its own building - and with no warehouse known every definition
 * is offered. Aisle narrows rows, aisle + row narrow bays. The server refuses anything else.
 */
export function useDefinedLocationPick(
  warehouseIds: (string | null | undefined)[],
  aisle: string,
  row: string,
  bay: string,
  skip = false,
): DefinedLocationPick {
  const { data } = useQuery<{ warehouseLocations: WarehouseLocationDef[] }>(GET_WAREHOUSE_LOCATIONS, {
    variables: { activeOnly: true },
    fetchPolicy: 'cache-and-network',
    skip,
  });
  const warehouseKey = Array.from(new Set(warehouseIds.filter((w): w is string => !!w)))
    .sort()
    .join('|');
  const definedHere = useMemo(() => {
    const warehouses = warehouseKey ? warehouseKey.split('|') : [];
    const byKey = new Map<string, { def: WarehouseLocationDef; in: Set<string> }>();
    for (const d of data?.warehouseLocations ?? []) {
      const key = `${d.aisle}|${d.row}|${d.bay}`;
      const entry = byKey.get(key) ?? { def: d, in: new Set<string>() };
      entry.in.add(d.warehouseId);
      byKey.set(key, entry);
    }
    return Array.from(byKey.values())
      .filter((e) => warehouses.every((w) => e.in.has(w)))
      .map((e) => e.def);
  }, [data, warehouseKey]);

  const options = useMemo(() => {
    const a = normalizeLocationValue(aisle);
    const r = normalizeLocationValue(row);
    const aisles = new Set<string>();
    const rows = new Set<string>();
    const bays = new Set<string>();
    for (const d of definedHere) {
      aisles.add(d.aisle);
      if (!a || d.aisle === a) rows.add(d.row);
      if ((!a || d.aisle === a) && (!r || d.row === r)) bays.add(d.bay);
    }
    const sort = (set: Set<string>) => Array.from(set).sort((x, y) => x.localeCompare(y));
    return { aisleOptions: sort(aisles), rowOptions: sort(rows), bayOptions: sort(bays) };
  }, [definedHere, aisle, row]);

  const isDefinedPick = useMemo(() => {
    const a = normalizeLocationValue(aisle);
    const r = normalizeLocationValue(row);
    const b = normalizeLocationValue(bay);
    return !!a && !!r && !!b && definedHere.some((d) => d.aisle === a && d.row === r && d.bay === b);
  }, [definedHere, aisle, row, bay]);

  const registryEmpty = !!data && definedHere.length === 0;

  return { ...options, isDefinedPick, registryEmpty };
}
