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

/**
 * #1912: a typed unit cost read whole, or NaN - never the leading digits of it. parseFloat stopped at the
 * first comma, so "1,250.00" saved as 1, and at the first stray letter, so "1250abc" saved as 1250. The
 * rule the average door cost box keeps: thousands commas, a dollar sign and spaces are how people write
 * money, so they are dropped, and anything else left over refuses the amount. Blank is NaN too.
 *
 * A comma counts only where a thousands comma goes - every three digits before the point. Dropped
 * wherever it sat, "12,50" written with a decimal comma read as 1250, a hundred times the price GP
 * would have been sent; it is refused as not a number instead.
 */
export function parseUnitCost(text: string): number {
  const cleaned = text.replace(/[$\s]/g, '');
  if (cleaned.includes(',') && !/^-?\d{1,3}(,\d{3})+(\.\d*)?$/.test(cleaned)) return NaN;
  const whole = cleaned.replace(/,/g, '');
  return whole === '' ? NaN : Number(whole);
}

/**
 * Why a typed unit cost can't be saved, or null when it can: not a whole number (#1912), negative, past
 * the cent (#1394), or past what the line's cost column holds (#1936). A $0 no-charge line is valid
 * (#1172). Worded short, for the error under a line's cost box.
 */
export function unitCostProblem(text: string): 'Not a number' | 'Must be >= 0' | 'To the cent' | 'Too large' | null {
  const cost = parseUnitCost(text);
  if (!Number.isFinite(cost)) return text.trim() ? 'Not a number' : 'Must be >= 0';
  if (cost < 0) return 'Must be >= 0';
  if (pastTheCent(text)) return 'To the cent';
  if (cost >= MAX_UNIT_COST) return 'Too large';
  return null;
}
