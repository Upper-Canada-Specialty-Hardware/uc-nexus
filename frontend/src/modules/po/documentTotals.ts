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
 * One line's extension, exact: quantity x unit cost, the figure GP itself stores per line (#1523). It is not
 * rounded to cents - GP keeps it to 5 places, and rounding each line before summing put the printed
 * subtotal a cent away from GP's on sub-cent prices (2 x 7 x $0.125 is $1.75 in GP, not $1.76).
 */
export function lineExtension(ordered: number | null | undefined, unitPrice: number | null | undefined): number {
  return (ordered ?? 0) * (unitPrice ?? 0);
}

/**
 * The goods subtotal as GP holds it and the register dialog shows it (computeRegisterTotals): the exact
 * line extensions summed, then rounded once to cents.
 */
export function documentSubtotal(
  lines: readonly { ordered: number | null | undefined; unitPrice: number | null | undefined }[],
): number {
  const exact = lines.reduce((sum, li) => sum + lineExtension(li.ordered, li.unitPrice), 0);
  // The small nudge keeps a sum like 1.005 (held as 1.00499...) rounding the way it reads.
  return (Math.sign(exact) * Math.round(Math.abs(exact) * 100 + 1e-7)) / 100;
}
