import { describe, it, expect } from 'vitest';
import { documentOrderTotal, documentSubtotal, lineExtension } from '../documentTotals';

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

describe('line extensions and the subtotal (#1523)', () => {
  it('sums the exact line extensions and rounds once, as GP holds the subtotal', () => {
    // GP stores each line's extension to 5 places and the relay sends it the unrounded sum: two lines of
    // 7 x $0.125 are $1.75 in GP and in the register dialog, so the document says $1.75 too.
    expect(lineExtension(7, 0.125)).toBe(0.875);
    expect(documentSubtotal([{ ordered: 7, unitPrice: 0.125 }, { ordered: 7, unitPrice: 0.125 }])).toBe(1.75);
  });

  it('keeps a sub-cent unit price whole across the quantity', () => {
    expect(lineExtension(1000, 0.0425)).toBeCloseTo(42.5);
    expect(documentSubtotal([{ ordered: 3, unitPrice: 1.005 }])).toBe(3.02);
    expect(documentSubtotal([{ ordered: null, unitPrice: 4 }])).toBe(0);
  });
});
