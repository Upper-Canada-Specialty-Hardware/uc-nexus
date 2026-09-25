import { linesBehindFigure, poShare, poTableHref } from '../viewPOs';
import type { ProductPOLine } from '../viewPOs';

function line(overrides: Partial<ProductPOLine>): ProductPOLine {
  return {
    poId: 'po-1',
    poNumber: 'PO-1',
    requestNumber: null,
    status: 'GP_REGISTERED',
    orderedQuantity: 0,
    receivedQuantity: 0,
    ...overrides,
  };
}

// The same three POs the backend test builds: the rollup gives on_order 8, received 9, so the wizard
// shows Ordered 17 (on_order + received) and On Order 8. The lists must sum to exactly those.
const LINES = [
  line({ poId: 'registered', status: 'GP_REGISTERED', orderedQuantity: 4 }),
  line({ poId: 'partial', status: 'PARTIALLY_RECEIVED', orderedQuantity: 6, receivedQuantity: 2 }),
  line({ poId: 'closed', status: 'CLOSED', orderedQuantity: 10, receivedQuantity: 7 }),
];

it('sums each list to the figure it sits beside', () => {
  const sum = (figure: 'ordered' | 'onOrder') =>
    linesBehindFigure(LINES, figure).reduce((total, r) => total + r.quantity, 0);
  expect(sum('ordered')).toBe(17);
  expect(sum('onOrder')).toBe(8);
});

it('counts a closed PO toward Ordered by what it received, and not toward On Order', () => {
  const closed = LINES[2];
  expect(poShare(closed, 'ordered')).toBe(7);
  expect(poShare(closed, 'onOrder')).toBe(0);
  expect(linesBehindFigure(LINES, 'onOrder').map((r) => r.line.poId)).toEqual(['registered', 'partial']);
});

it('leaves out an open PO that has fully arrived from the On Order list', () => {
  const arrived = line({ status: 'VENDOR_CONFIRMED', orderedQuantity: 3, receivedQuantity: 3 });
  expect(linesBehindFigure([arrived], 'onOrder')).toEqual([]);
  expect(linesBehindFigure([arrived], 'ordered')).toHaveLength(1);
});

it('links into the PO table with the PO open', () => {
  expect(poTableHref('abc-123')).toBe('/app/po?po=abc-123');
});
