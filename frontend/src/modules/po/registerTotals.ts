/**
 * The totals the Register PO in GP dialog shows before anything is sent (#858): what the lines add up
 * to, the tax GP is likely to charge, the header charges, and the total.
 *
 * The tax is an ESTIMATE, and it is worked the way the relay writes it at PO REGISTRATION (#762, the
 * relay's po_tax): the trade discount comes off the goods before tax, and the freight and the misc are
 * taxed at every detail of the schedule too, because a PO that carries a tax detail at all taxes both
 * charges. Kept simple on purpose: one rounding per detail on the whole base, where GP rounds per line
 * per detail, so it can land a cent or two off the amount GP calculates.
 */

export interface RegisterTotalsInput {
  lines: { orderedQuantity: string; unitCost: string }[];
  freight: string;
  miscellaneous: string;
  tradeDiscount: string;
  /**
   * The percent of each purchase detail on the picked tax schedule. Null when no schedule is known -
   * none picked yet, or one typed by hand whose rates GP has not told us - and the tax is then unknown.
   * An empty list means no tax at all (a foreign-currency PO carries no schedule).
   */
  taxPercents: number[] | null;
}

export interface RegisterTotals {
  subtotal: number;
  tradeDiscount: number;
  freight: number;
  miscellaneous: number;
  /** Null when the tax is unknown (see taxPercents). */
  tax: number | null;
  /** Everything above, less the trade discount. Before tax when the tax is unknown. */
  total: number;
}

/** A money box's text as a number: blank or not a number counts as nothing entered. */
function amount(text: string): number {
  const n = parseFloat(text);
  return Number.isFinite(n) ? n : 0;
}

function cents(n: number): number {
  return Math.round((n + Number.EPSILON) * 100) / 100;
}

export function computeRegisterTotals(input: RegisterTotalsInput): RegisterTotals {
  const subtotal = cents(
    input.lines.reduce((sum, li) => sum + amount(li.orderedQuantity) * amount(li.unitCost), 0),
  );
  const tradeDiscount = cents(amount(input.tradeDiscount));
  const freight = cents(amount(input.freight));
  const miscellaneous = cents(amount(input.miscellaneous));
  const base = Math.max(subtotal - tradeDiscount, 0) + freight + miscellaneous;
  const tax =
    input.taxPercents === null
      ? null
      : cents(input.taxPercents.reduce((sum, pct) => sum + cents((base * pct) / 100), 0));
  const total = cents(subtotal - tradeDiscount + freight + miscellaneous + (tax ?? 0));
  return { subtotal, tradeDiscount, freight, miscellaneous, tax, total };
}

export function formatMoney(value: number): string {
  return value.toLocaleString('en-CA', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}
