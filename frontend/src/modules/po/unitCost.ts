/**
 * #1394: GP keeps a PO line's unit cost to the cent and refuses more places at the line, so every form
 * that takes a unit cost checks the text as typed. Trailing zeros are fine: 12.50 and 12.500 are to
 * the cent, 0.333 is not.
 */
export function pastTheCent(text: string): boolean {
  return (text.trim().split('.')[1] ?? '').replace(/0+$/, '').length > 2;
}

/** #1936: a line's unit cost column is Numeric(19,5), so the server refuses anything at or above this. */
export const MAX_UNIT_COST = 1e14;
