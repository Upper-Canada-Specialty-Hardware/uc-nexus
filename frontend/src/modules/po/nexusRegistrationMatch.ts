// Reading a GP line's description well enough to guess which schedule product it is for. Pure, so
// the Nexus Registration panel stays a component file and this stays unit-testable.

export interface ScheduleProduct {
  projectId: string;
  hardwareCategory: string;
  productCode: string;
  classification: string | null;
  requiredQuantity: number;
  // The slice of requiredQuantity still on no purchase order - the ceiling on a line's tie quantity.
  availableQuantity: number;
}

/** The key a schedule product is picked by. Two segments, separated by something no product code or
 *  category contains, so a key never splits ambiguously. */
export const productKeyOf = (p: { hardwareCategory: string; productCode: string }) =>
  `${p.hardwareCategory} :: ${p.productCode}`;

/** Lower-cased with every run of whitespace collapsed to one space, so "HD 001  HINGE" and
 *  "hd 001 hinge" compare equal and a product code can be found inside a GP description. */
export function collapseForMatch(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

/** The schedule product a GP description looks like it is for: the one whose product code appears in
 *  the description. Null when no code appears. When several do, the longest wins - it is the most
 *  specific reading of the same description. */
export function suggestScheduleProduct(
  gpDescription: string,
  products: ScheduleProduct[],
): ScheduleProduct | null {
  const haystack = collapseForMatch(gpDescription);
  if (!haystack) return null;
  const hits = products.filter((p) => {
    const needle = collapseForMatch(p.productCode);
    return needle.length > 0 && haystack.includes(needle);
  });
  if (hits.length === 0) return null;
  return hits.reduce((best, p) => (p.productCode.length > best.productCode.length ? p : best));
}
