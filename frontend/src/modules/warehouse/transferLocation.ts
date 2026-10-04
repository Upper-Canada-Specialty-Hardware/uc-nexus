/** Where a transfer source sits, as the server stores it. */
export interface LocatedSource {
  warehouseId: string | null;
  aisle?: string | null;
  row?: string | null;
  bay?: string | null;
}

/** A location part as the server compares it (`normalize_location_value`): uppercased, trimmed, inner
 *  whitespace collapsed, and blank read as no value at all. */
export function normalizeLocationPart(value: string | null | undefined): string | null {
  if (value == null) return null;
  const normalized = value.toUpperCase().trim().split(/\s+/).join(' ');
  return normalized || null;
}

/** Whether a source already sits in the destination bin - the server's own same-location refusal
 *  (`transfer_inventory`, #1451): same warehouse, and the stored aisle/row/bay equal to the normalized
 *  destination. A source missing a part never matches, since a destination needs all three. */
export function isAtDestination(
  s: LocatedSource,
  destWarehouseId: string,
  aisle: string,
  row: string,
  bay: string,
): boolean {
  return (
    !!destWarehouseId &&
    s.warehouseId === destWarehouseId &&
    normalizeLocationPart(s.aisle) === normalizeLocationPart(aisle) &&
    normalizeLocationPart(s.row) === normalizeLocationPart(row) &&
    normalizeLocationPart(s.bay) === normalizeLocationPart(bay)
  );
}
