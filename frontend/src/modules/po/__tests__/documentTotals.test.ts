import { describe, it, expect } from 'vitest';
import { documentOrderTotal } from '../documentTotals';

describe('documentOrderTotal (#1236)', () => {
  it('takes the trade discount off the goods', () => {
    // A $1,000 PO with $100 off: GP holds $900 plus the charges, and so does the document now.
    expect(
      documentOrderTotal({
        subtotal: 1000, tradeDiscount: 100, freight: 50, miscellaneous: 0, taxAmount: 123.5, tariffAmount: 0,
      }),
    ).toBeCloseTo(1073.5);
  });

  it('reads a missing discount as none', () => {
    expect(
      documentOrderTotal({ subtotal: 1000, freight: 50, miscellaneous: 10, taxAmount: 0, tariffAmount: 5 }),
    ).toBeCloseTo(1065);
  });
});
