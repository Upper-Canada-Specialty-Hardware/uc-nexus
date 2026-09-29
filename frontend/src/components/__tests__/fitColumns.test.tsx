import { fireEvent, render, screen } from '@testing-library/react';
import { TableCell, TableRow } from '@mui/material';
import { layoutColumns, resizeColumn, resolveWeights, type FitColumn } from '../fitColumns';
import FitTable, { type FitTableColumn } from '../FitTable';

const COLUMNS: FitColumn[] = [
  { id: 'a', label: 'A', min: 100, weight: 2 },
  { id: 'b', label: 'B', min: 50, weight: 1 },
  { id: 'c', label: 'C', min: 50, weight: 1 },
  { id: 'act', label: 'Actions', min: 40, fixed: 40 },
];

const sum = (xs: number[]) => xs.reduce((a, b) => a + b, 0);

describe('fitColumns layout (#856)', () => {
  it('shares the free width by weight and always adds up to the table width', () => {
    const px = layoutColumns(COLUMNS, resolveWeights(COLUMNS, {}), 440);
    expect(px).toEqual([200, 100, 100, 40]);
    expect(sum(px)).toBe(440);
  });

  it('holds a column at its minimum and re-shares the rest', () => {
    // 400 free: A's 10% share would be 40, under its 100 minimum, so it holds at 100 and B and C
    // split the other 300.
    const px = layoutColumns(COLUMNS, resolveWeights(COLUMNS, { a: 0.1, b: 0.45, c: 0.45 }), 440);
    expect(px[0]).toBe(100);
    expect(px[1]).toBeCloseTo(150);
    expect(px[2]).toBeCloseTo(150);
    expect(sum(px)).toBeCloseTo(440);
  });

  it('scales every column down when even the minimums do not fit, so the table still fits', () => {
    const px = layoutColumns(COLUMNS, resolveWeights(COLUMNS, {}), 200);
    expect(sum(px)).toBeCloseTo(200);
    expect(px[3]).toBe(40);
  });

  it('widens one column by taking from the others, each only down to its minimum', () => {
    const weights = resolveWeights(COLUMNS, {});
    const grown = resizeColumn(COLUMNS, weights, 0, 60, 440);
    let px = layoutColumns(COLUMNS, resolveWeights(COLUMNS, grown), 440);
    expect(px[0]).toBeCloseTo(260);
    // The others gave the 60 between them, in proportion to their widths.
    expect(px[1]).toBeCloseTo(70);
    expect(px[2]).toBeCloseTo(70);

    // Past what they can give: they stop at their minimums and A takes only the rest.
    const maxed = resizeColumn(COLUMNS, weights, 0, 1000, 440);
    px = layoutColumns(COLUMNS, resolveWeights(COLUMNS, maxed), 440);
    expect(px).toEqual([300, 50, 50, 40].map((v) => expect.closeTo(v)));
  });

  it('never shrinks a column under its own minimum', () => {
    const shrunk = resizeColumn(COLUMNS, resolveWeights(COLUMNS, {}), 1, -1000, 440);
    const px = layoutColumns(COLUMNS, resolveWeights(COLUMNS, shrunk), 440);
    expect(px[1]).toBeCloseTo(50);
    expect(sum(px)).toBeCloseTo(440);
  });
});

// ---- FitTable ----

function stubWidth(width: number) {
  vi.stubGlobal(
    'ResizeObserver',
    class {
      private cb: ResizeObserverCallback;
      constructor(cb: ResizeObserverCallback) {
        this.cb = cb;
      }
      observe() {
        this.cb([{ contentRect: { width } } as ResizeObserverEntry], this as unknown as ResizeObserver);
      }
      unobserve() {}
      disconnect() {}
    },
  );
}

const TABLE_COLUMNS: FitTableColumn[] = [
  { id: 'name', label: 'Name', min: 100, weight: 2 },
  { id: 'qty', label: 'Qty', min: 50, weight: 1 },
  { id: 'act', label: 'Actions', min: 40, fixed: 40, header: null },
];

function renderTable() {
  return render(
    <FitTable storageKey="test-table" columns={TABLE_COLUMNS}>
      <TableRow>
        <TableCell>widget</TableCell>
        <TableCell>3</TableCell>
        <TableCell>go</TableCell>
      </TableRow>
    </FitTable>,
  );
}

describe('FitTable (#856)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('fits its width with a fixed layout and no sideways scroll', () => {
    stubWidth(340);
    const { container } = renderTable();

    const box = container.querySelector('[data-fit-table="test-table"]') as HTMLElement;
    expect(['auto', 'scroll']).not.toContain(getComputedStyle(box).overflowX);
    expect(getComputedStyle(box.querySelector('table') as HTMLElement).tableLayout).toBe('fixed');
    const cols = Array.from(container.querySelectorAll('col')).map((c) => parseFloat(c.style.width));
    expect(cols).toEqual([200, 100, 40]);
  });

  it('offers a named, focusable resize handle per resizable column, none on a fixed one', () => {
    stubWidth(340);
    renderTable();

    const handles = screen.getAllByRole('separator');
    expect(handles.map((h) => h.getAttribute('aria-label'))).toEqual(['Resize Name column', 'Resize Qty column']);
    for (const h of handles) expect(h).toHaveAttribute('tabindex', '0');
  });

  it('resizes by drag and by arrow keys', () => {
    stubWidth(340);
    const { container } = renderTable();
    const handle = screen.getByRole('separator', { name: 'Resize Name column' });
    const colWidths = () => Array.from(container.querySelectorAll('col')).map((c) => parseFloat(c.style.width));

    fireEvent.keyDown(handle, { key: 'ArrowLeft' });
    expect(colWidths()[0]).toBeCloseTo(184);
    expect(colWidths()[1]).toBeCloseTo(116);

    fireEvent.pointerDown(handle, { clientX: 100, pointerId: 1 });
    fireEvent.pointerMove(handle, { clientX: 130, pointerId: 1 });
    fireEvent.pointerUp(handle, { clientX: 130, pointerId: 1 });
    expect(colWidths()[0]).toBeCloseTo(214);
    expect(colWidths()[1]).toBeCloseTo(86);
    expect(colWidths()[0] + colWidths()[1] + colWidths()[2]).toBeCloseTo(340);
  });
});
