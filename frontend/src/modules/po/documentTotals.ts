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
