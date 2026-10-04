import { render, screen } from '@testing-library/react';
import type { GridColumnHeaderParams } from '@mui/x-data-grid';
import { buildColumns } from '../hardwareStatusColumns';

// #1403: at 1366px with the nav rail expanded the page content is 1366 - 224 (rail) - 48 (gutters) =
// 1094px. The grid spends 2px on borders and useGridColumnFit keeps 18px for a scrollbar, so the column
// floors must sum to 1074px or less - past that the fit squeezes every column under its floor and the
// headers clip.
const CONTENT_AT_1366 = 1366 - 224 - 48;
const FLOOR_BUDGET = CONTENT_AT_1366 - 2 - 18;

it.each([true, false])('column floors fit 1366 with the rail expanded (anySchedule=%s)', (anySchedule) => {
  const columns = buildColumns(anySchedule);
  const sum = columns.reduce((total, c) => total + (c.minWidth ?? 0), 0);
  expect(columns.every((c) => (c.minWidth ?? 0) > 0)).toBe(true);
  expect(sum).toBeLessThanOrEqual(FLOOR_BUDGET);
});

it('labels the returned column short and keeps the full meaning in its tooltip', () => {
  const returned = buildColumns(true).find((c) => c.field === 'returnedToProject');
  expect(returned?.headerName).toBe('Returned');
  render(<>{returned?.renderHeader?.({} as GridColumnHeaderParams)}</>);
  expect(screen.getByText('Returned')).toBeInTheDocument();
  expect(screen.getByLabelText(/^Returned to project:/)).toBeInTheDocument();
});
