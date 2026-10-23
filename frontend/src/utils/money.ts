/**
 * #1912: a typed amount of money read whole, or NaN - never the leading digits of it. parseFloat stopped
 * at the first comma, so "1,250.00" saved as 1, and at the first stray letter, so "1250abc" saved as
 * 1250. A dollar sign and spaces are how people write money, so they are dropped; so is a thousands
 * comma, but only where one goes - every three digits before the point. Dropped wherever it sat, "12,50"
 * written with a decimal comma read as 1250, a hundred times the amount meant. Only digits, those commas,
 * one point and a leading minus are read: Number alone took "1e3" as 1000 and "0x10" as 16. Blank is NaN.
 */
export function parseMoney(text: string): number {
  const cleaned = text.replace(/[$\s]/g, '');
  if (!/^-?(\d{1,3}(,\d{3})+|\d*)(\.\d*)?$/.test(cleaned) || !/\d/.test(cleaned)) return NaN;
  return Number(cleaned.replace(/,/g, ''));
}
