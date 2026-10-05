/**
 * Natural order for location parts and labels (#1569): aisle, row and bay are stored as text, so a plain
 * compare put A-1-10 before A-1-2 and offered bays 1, 10, 11, 12, 2. Digit runs compare as numbers, case is
 * ignored, and a missing value sorts first.
 */
export function naturalCompare(a: string | null | undefined, b: string | null | undefined): number {
  return (a ?? '').localeCompare(b ?? '', undefined, { numeric: true, sensitivity: 'base' });
}

/** Aisle, then row, then bay, each in natural order. */
export function compareLocations(
  a: { aisle?: string | null; row?: string | null; bay?: string | null },
  b: { aisle?: string | null; row?: string | null; bay?: string | null },
): number {
  return naturalCompare(a.aisle, b.aisle) || naturalCompare(a.row, b.row) || naturalCompare(a.bay, b.bay);
}

/** A grid column's `sortComparator` for a joined location label ("A-1-10", "A / 1 / 10"). */
export const naturalSortComparator = (v1: unknown, v2: unknown): number =>
  naturalCompare(v1 == null ? '' : String(v1), v2 == null ? '' : String(v2));
