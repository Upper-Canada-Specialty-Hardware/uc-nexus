import { computeRegisterTotals } from '../registerTotals';

// #858: the totals the register dialog shows before anything is sent to GP.
describe('computeRegisterTotals', () => {
  const lines = [
    { orderedQuantity: '10', unitCost: '2.5' },
    { orderedQuantity: '3', unitCost: '19.99' },
  ];

  it('sums qty x unit cost and taxes goods, freight and misc at every detail', () => {
    const t = computeRegisterTotals({
      lines,
      freight: '10',
      miscellaneous: '4',
      tradeDiscount: '',
      taxPercents: [5, 7],
    });
    // 25.00 + 59.97 = 84.97; base 98.97; 5% = 4.95, 7% = 6.93
    expect(t.subtotal).toBe(84.97);
    expect(t.tax).toBe(11.88);
    expect(t.total).toBe(110.85);
  });

  it('takes the trade discount off the goods before tax', () => {
    const t = computeRegisterTotals({
      lines: [{ orderedQuantity: '1', unitCost: '100' }],
      freight: '',
      miscellaneous: '',
      tradeDiscount: '20',
      taxPercents: [13],
    });
    expect(t.tax).toBe(10.4);
    expect(t.total).toBe(90.4);
  });

  it('leaves the tax unknown with no schedule, and zero with none to charge', () => {
    const unknown = computeRegisterTotals({ lines, freight: '', miscellaneous: '', tradeDiscount: '', taxPercents: null });
    expect(unknown.tax).toBeNull();
    expect(unknown.total).toBe(84.97);
    const none = computeRegisterTotals({ lines, freight: '', miscellaneous: '', tradeDiscount: '', taxPercents: [] });
    expect(none.tax).toBe(0);
  });

  it('counts a box that is blank or not a number as nothing entered', () => {
    const t = computeRegisterTotals({
      lines: [{ orderedQuantity: 'TBD', unitCost: '5' }, { orderedQuantity: '2', unitCost: '' }],
      freight: 'abc',
      miscellaneous: '',
      tradeDiscount: '',
      taxPercents: [13],
    });
    expect(t.subtotal).toBe(0);
    expect(t.total).toBe(0);
  });
});
