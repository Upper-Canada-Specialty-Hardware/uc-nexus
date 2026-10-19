import type { PackingSlipHeader } from './deliveryRequest';

/** The load picker's value for "start a new load" (#1720). */
export const NEW_LOAD = '';

/** A YYYY-MM-DD calendar day as "Oct 15". Built from its parts: `new Date('2026-10-15')` is UTC
 *  midnight, which is the 14th anywhere west of Greenwich. */
export function fmtShipDate(day: string): string {
  const [y, m, d] = day.split('-').map(Number);
  return new Date(y, m - 1, d).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

/**
 * The other slips on this slip's load, as "PS-00413 (23001)" (#1724). A cancelled slip is left out:
 * it is on the load as history, not on the truck.
 */
export function ridingWith(slip: Pick<PackingSlipHeader, 'id' | 'load'>): string[] {
  return (slip.load?.slips ?? [])
    .filter((s) => s.id !== slip.id && s.status !== 'CANCELLED')
    .map((s) => `${s.packingSlipNumber} (${s.projectNumber})`);
}
