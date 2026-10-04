import { it, expect } from 'vitest';
import type { GridColDef } from '@mui/x-data-grid';
import { columnMinWidth } from '../../../components/useGridColumnFit';
import { buildRelayInstallColumns } from '../relayInstallsColumns';

// #1429: at 1366px with the nav rail expanded the page content is 1366 - 224 (rail) - 48 (gutters) =
// 1094px. The grid spends 2px on borders and useGridColumnFit keeps 18px for a scrollbar, so the floors -
// a fixed column at its full width - must sum to 1074px or less, or every column is squeezed under its
// value.
const FLOOR_BUDGET = 1366 - 224 - 48 - 2 - 18;

const floor = (c: GridColDef) =>
  c.resizable === false && c.width !== undefined && !c.flex ? c.width : columnMinWidth(c);

it('fits 1366 with the rail expanded', () => {
  const columns = buildRelayInstallColumns({ liveInstallId: null, onCopy: () => {}, onAdopt: () => {}, onRemove: () => {} });
  expect(columns.reduce((sum, c) => sum + floor(c), 0)).toBeLessThanOrEqual(FLOOR_BUDGET);
});

it('keeps the install history reachable in one column', () => {
  const columns = buildRelayInstallColumns({ liveInstallId: null, onCopy: () => {}, onAdopt: () => {}, onRemove: () => {} });
  const headers = columns.map((c) => c.headerName);
  expect(headers).toContain('History');
  expect(headers).toContain('Last seen');
  expect(headers).not.toContain('Adopted by');
});
