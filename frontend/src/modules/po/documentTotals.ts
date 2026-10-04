/**
 * The generated PO document's order total (#1236): the goods less GP's trade discount, plus the header
 * charges. The discount comes off the goods the way GP holds it and the register dialog's totals
 * (computeRegisterTotals) take it; a document without one reads as no discount.
 */
export interface DocumentTotalsInput {
  subtotal: number;
  freight: number;
  miscellaneous: number;
  taxAmount: number;
  tariffAmount: number;
  tradeDiscount?: number;
}

export function documentOrderTotal(t: DocumentTotalsInput): number {
  return (
    t.subtotal - (t.tradeDiscount ?? 0) + (t.freight ?? 0) + (t.miscellaneous ?? 0) + (t.taxAmount ?? 0)
    + (t.tariffAmount ?? 0)
  );
}

/**
 * One line's extension as the document prints it and GP holds it: rounded to cents (#1523). The subtotal
 * is the sum of these, so the Ext. column adds up to the Subtotal printed under it - summing the unrounded
 * products could land a cent away from both the column and GP's total on a sub-cent unit price.
 */
export function lineExtension(ordered: number | null | undefined, unitPrice: number | null | undefined): number {
  const exact = (ordered ?? 0) * (unitPrice ?? 0);
  // The small nudge keeps a product like 1.005 (stored as 1.00499...) rounding the way it reads.
  return (Math.sign(exact) * Math.round(Math.abs(exact) * 100 + 1e-7)) / 100;
}

export function documentSubtotal(
  lines: readonly { ordered: number | null | undefined; unitPrice: number | null | undefined }[],
): number {
  return Math.round(lines.reduce((sum, li) => sum + lineExtension(li.ordered, li.unitPrice) * 100, 0)) / 100;
}
