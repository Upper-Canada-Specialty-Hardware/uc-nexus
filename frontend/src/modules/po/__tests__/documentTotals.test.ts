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
  it('rounds each line to cents, so the Ext. column adds up to the subtotal', () => {
    // 7 x $0.125 is $0.875 a line: each prints $0.88, and two of them are $1.76, as GP holds it - not $1.75.
    expect(lineExtension(7, 0.125)).toBe(0.88);
    expect(documentSubtotal([{ ordered: 7, unitPrice: 0.125 }, { ordered: 7, unitPrice: 0.125 }])).toBe(1.76);
  });

  it('keeps a sub-cent unit price whole across the quantity', () => {
    expect(lineExtension(1000, 0.0425)).toBe(42.5);
    expect(lineExtension(3, 1.005)).toBe(3.02);
    expect(lineExtension(null, 4)).toBe(0);
  });
});
