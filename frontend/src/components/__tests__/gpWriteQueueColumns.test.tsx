import { it, expect } from 'vitest';
import { render, screen } from '@testing-library/react';
import type { GridColDef, GridRenderCellParams } from '@mui/x-data-grid';
import { columnMinWidth } from '../useGridColumnFit';
import { buildGpWriteQueueColumns, type OutboxEntry } from '../gpWriteQueueColumns';

// #1429: 1366 - 224 (rail) - 48 (gutters) - 2 (borders) - 18 (scrollbar allowance). The admin queue is
// a full-width grid on the relay installs page; the compact mounting sits inside module pages that are
// no wider.
const FLOOR_BUDGET = 1366 - 224 - 48 - 2 - 18;

const floor = (c: GridColDef) =>
  c.resizable === false && c.width !== undefined && !c.flex ? c.width : columnMinWidth(c);

const options = { canActOn: () => true, gateReason: () => '', onRetry: () => {}, onCancel: () => {} };

it.each([false, true])('fits 1366 with the rail expanded (compact=%s)', (compact) => {
  const columns = buildGpWriteQueueColumns({ ...options, compact });
  expect(columns.reduce((sum, c) => sum + floor(c), 0)).toBeLessThanOrEqual(FLOOR_BUDGET);
});

it('reads the failure kind together with the error it explains', () => {
  const lastError = buildGpWriteQueueColumns(options).find((c) => c.field === 'lastError');
  const row = { failureKind: 'gp_rejected', lastError: 'Vendor is on hold' } as OutboxEntry;
  render(<>{lastError?.renderCell?.({ row } as GridRenderCellParams)}</>);
  expect(screen.getByText('gp_rejected')).toBeInTheDocument();
  expect(screen.getByText('Vendor is on hold')).toBeInTheDocument();
});
