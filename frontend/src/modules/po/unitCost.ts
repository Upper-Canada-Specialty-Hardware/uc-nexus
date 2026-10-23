import { parseMoney } from '../../utils/money';

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

/** #1912: a typed unit cost read whole, or NaN - the money rule every typed amount keeps (`parseMoney`). */
export function parseUnitCost(text: string): number {
  return parseMoney(text);
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
