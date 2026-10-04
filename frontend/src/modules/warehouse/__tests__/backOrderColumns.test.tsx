import { it, expect } from 'vitest';
import { columnMinWidth } from '../../../components/useGridColumnFit';
import { backOrderColumns } from '../backOrderColumns';

// #1429: 1366 - 224 (rail) - 48 (gutters) - 2 (borders) - 18 (scrollbar allowance). The back-order grid
// is full width on the Receiving page and has no checkbox column.
const FLOOR_BUDGET = 1366 - 224 - 48 - 2 - 18;

it('fits 1366 with the rail expanded', () => {
  expect(backOrderColumns.reduce((sum, c) => sum + columnMinWidth(c), 0)).toBeLessThanOrEqual(FLOOR_BUDGET);
});

it('keeps ordered and received beside outstanding', () => {
  const fields = backOrderColumns.map((c) => c.field);
  expect(fields).toEqual(expect.arrayContaining(['orderedQuantity', 'receivedQuantity', 'outstandingQuantity']));
});
