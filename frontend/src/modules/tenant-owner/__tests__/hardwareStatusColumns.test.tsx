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

// #1483: a wrapped header gets two lines (HEADER_HEIGHT); a third is cut off below the header row.
// Lines are counted the way the header wraps them, in letters: the floors' own calibration (80 fits a
// 7-letter word, 86 an 8-letter one, 96 a 9-letter one) with the (i) marker leading the first line at
// about one letter wide and no space after it. Measured on production at 1366: "(i) STAGED" on one
// line, "(i) SENT / TO SHOP" on two, and "Shipped Out" at 80 on three - (i) / SHIPPED / OUT.
const lettersPerLine = (floor: number) => Math.floor((floor - 30) / 7);

function headerLines(label: string, floor: number): number {
  const cap = lettersPerLine(floor);
  let lines = 1;
  let used = 1; // the (i) marker
  let afterMarker = true;
  for (const word of label.toUpperCase().split(/\s+/)) {
    const needed = used + (afterMarker ? 0 : 1) + word.length;
    if (needed <= cap) {
      used = needed;
    } else {
      lines += 1;
      used = word.length;
    }
    afterMarker = false;
  }
  return lines;
}

it('counts header lines the way production wrapped them', () => {
  expect(headerLines('Staged', 80)).toBe(1);
  expect(headerLines('Sent to Shop', 80)).toBe(2);
  expect(headerLines('Received', 86)).toBe(2);
  expect(headerLines('Not Purchased', 96)).toBe(2);
  expect(headerLines('Shipped Out', 80)).toBe(3);
});

it.each([true, false])('every count header fits two lines at its floor (anySchedule=%s)', (anySchedule) => {
  const tooTall = buildColumns(anySchedule)
    .filter((c) => c.type === 'number')
    .map((c) => ({ field: c.field, lines: headerLines(c.headerName ?? '', c.minWidth ?? 0) }))
    .filter((h) => h.lines > 2);
  expect(tooTall).toEqual([]);
});
