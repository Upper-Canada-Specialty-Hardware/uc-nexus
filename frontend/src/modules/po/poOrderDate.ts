// A PO's Order Date is GP's document date off the PO header - a calendar date, which the backend
// stores and serves as one (#701). GP writes 1900-01-01 on a header nobody dated, and the mirror
// stores that exactly as GP holds it rather than turning it into nothing on the way in: GP is the
// authority for the GP-OWNED FIELDS and the copy is overwritten, never compared. Reading 1900-01-01
// back as what it means is therefore this module's job, and every screen that prints an order date
// goes through it so they all say the same thing.
import { parseServerDay } from '../../utils/serverDate';

/** GP's stand-in for a document date nobody filled in. */
const GP_EMPTY_DATE = '1900-01-01';

/** What the PO table and the PO detail dialog print in place of GP's empty document date. */
export const NO_GP_DATE = 'No date in GP';

/** The hover beside those words, which says whose gap it is. */
export const NO_GP_DATE_HINT = 'GP holds an empty document date on this PO.';

/**
 * Is this order date GP's empty one? True for 1900-01-01 and for anything earlier, which is no date
 * a person entered either.
 */
export function isGpEmptyDate(orderedAt: string | null | undefined): boolean {
  const day = /^\d{4}-\d{2}-\d{2}/.exec(orderedAt ?? '')?.[0];
  return day !== undefined && day <= GP_EMPTY_DATE;
}

/**
 * The order date as a screen prints it: a dash when the PO has none at all, the plain words when
 * GP's is empty, and otherwise the calendar day in the viewer's own locale.
 */
export function formatPoOrderDate(orderedAt: string | null | undefined): string {
  if (!orderedAt) return '-';
  if (isGpEmptyDate(orderedAt)) return NO_GP_DATE;
  return parseServerDay(orderedAt).toLocaleDateString();
}
