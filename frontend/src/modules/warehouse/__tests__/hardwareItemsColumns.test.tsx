import { it, expect } from 'vitest';
import type { GridColDef } from '@mui/x-data-grid';
import { CHECKBOX_COL_WIDTH, columnMinWidth } from '../../../components/useGridColumnFit';
import { buildHardwareItemColumns, HARDWARE_ITEMS_DEFAULT_HIDDEN } from '../hardwareItemsColumns';

// #1429: 1366 - 224 (rail) - 48 (gutters) - 2 (borders) - 18 (scrollbar allowance), less the checkbox
// column this grid always shows. The columns it starts with hidden take no width.
const FLOOR_BUDGET = 1366 - 224 - 48 - 2 - 18 - CHECKBOX_COL_WIDTH;

const hidden = HARDWARE_ITEMS_DEFAULT_HIDDEN as Record<string, boolean>;
const visibleFloorSum = (columns: GridColDef[]) =>
  columns.filter((c) => hidden[c.field] !== false).reduce((sum, c) => sum + columnMinWidth(c), 0);

it.each([
  ['one project', 'project-1'],
  ['all projects', undefined],
])('fits 1366 with the rail expanded (%s)', (_label, projectId) => {
  const columns = buildHardwareItemColumns(projectId) as GridColDef[];
  expect(visibleFloorSum(columns)).toBeLessThanOrEqual(FLOOR_BUDGET);
});

it('keeps the deficient count as a column, hidden at first, and the vendor searchable', () => {
  const columns = buildHardwareItemColumns(undefined) as GridColDef[];
  expect(columns.some((c) => c.field === 'deficient')).toBe(true);
  expect(hidden.deficient).toBe(false);
  const po = columns.find((c) => c.field === 'poNumber');
  const value = (po?.valueGetter as unknown as (v: unknown, row: object) => string)(null, {
    poNumber: 'PO-1001',
    vendorName: 'Acme Hardware',
  });
  expect(value).toBe('PO-1001 · Acme Hardware');
});
