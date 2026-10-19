/** The load picker's value for "start a new load" (#1720). */
export const NEW_LOAD = '';

/** A YYYY-MM-DD calendar day as "Oct 15". Built from its parts: `new Date('2026-10-15')` is UTC
 *  midnight, which is the 14th anywhere west of Greenwich. */
export function fmtShipDate(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}
