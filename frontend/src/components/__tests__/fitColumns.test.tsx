import { fireEvent, render, screen } from '@testing-library/react';
import { TableCell, TableRow } from '@mui/material';
import { distribute, layoutColumns, resizeColumn, resolveWeights, type FitColumn } from '../fitColumns';
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

describe('FitTable options (#909)', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('renders a footer inside the box and keeps aria-sort on a sorted header', () => {
    stubWidth(340);
    const columns: FitTableColumn[] = [{ ...TABLE_COLUMNS[0], sortDirection: 'desc' }, ...TABLE_COLUMNS.slice(1)];
    const { container } = render(
      <FitTable storageKey="test-footer" columns={columns} footer={<div>page 1 of 2</div>}>
        <TableRow>
          <TableCell>widget</TableCell>
          <TableCell>3</TableCell>
          <TableCell>go</TableCell>
        </TableRow>
      </FitTable>,
    );

    const box = container.querySelector('[data-fit-table="test-footer"]') as HTMLElement;
    expect(box).toContainElement(screen.getByText('page 1 of 2'));
    expect(screen.getAllByRole('columnheader')[0]).toHaveAttribute('aria-sort', 'descending');
  });

  it('scrolls a height-capped box up and down only, under a sticky header', () => {
    stubWidth(340);
    const { container } = render(
      <FitTable storageKey="test-capped" columns={TABLE_COLUMNS} maxHeight={200}>
        <TableRow>
          <TableCell>widget</TableCell>
          <TableCell>3</TableCell>
          <TableCell>go</TableCell>
        </TableRow>
      </FitTable>,
    );

    const box = container.querySelector('[data-fit-table="test-capped"]') as HTMLElement;
    expect(getComputedStyle(box).overflowX).toBe('hidden');
    expect(getComputedStyle(box).overflowY).toBe('auto');
    expect(screen.getAllByRole('separator')).toHaveLength(2);
  });
});

describe('fitColumns protected columns (#1322)', () => {
  const close = (a: number, b: number) => expect(a).toBeCloseTo(b, 6);

  it('without a protected column, an overfull table scales every column by its minimum (unchanged)', () => {
    const px = distribute(300, [1, 1, 1], [200, 100, 100]);
    close(sum(px), 300);
    close(px[0], 150);
    close(px[1], 75);
    close(px[2], 75);
    expect(distribute(300, [1, 1, 1], [200, 100, 100], [false, false, false])).toEqual(px);
  });

  it('keeps a protected column at its minimum and takes the shortfall from the others', () => {
    // The receive lines at 768px: 184 protected + 532 of text minimums into 622.
    const mins = [112, 100, 100, 72, 80, 68, 184];
    const px = distribute(
      622,
      mins.map(() => 1),
      mins,
      [false, false, false, false, false, false, true],
    );
    close(sum(px), 622);
    close(px[6], 184);
    for (let i = 0; i < 6; i += 1) close(px[i], (mins[i] / 532) * 438);
  });

  it('keeps several protected columns whole while the others still have width to give', () => {
    const px = distribute(
      460,
      [1, 1, 1, 1, 1, 1],
      [80, 56, 80, 88, 248, 72],
      [false, false, false, false, true, true],
    );
    close(sum(px), 460);
    close(px[4], 248);
    close(px[5], 72);
    close(px[0] + px[1] + px[2] + px[3], 140);
  });

  it('falls back to proportional scaling when the protected minimums alone do not fit', () => {
    const px = distribute(200, [1, 1, 1], [50, 150, 100], [false, true, true]);
    close(sum(px), 200);
    close(px[0], (50 / 300) * 200);
    close(px[1], (150 / 300) * 200);
    close(px[2], (100 / 300) * 200);
  });

  it('falls back to proportional scaling when every column is protected', () => {
    const px = distribute(150, [1, 1], [100, 100], [true, true]);
    close(px[0], 75);
    close(px[1], 75);
  });

  it('changes nothing while the minimums fit', () => {
    const plain = distribute(600, [2, 1, 1], [100, 50, 50]);
    expect(distribute(600, [2, 1, 1], [100, 50, 50], [false, true, false])).toEqual(plain);
  });

  it('layoutColumns passes the protect flag through beside fixed columns and still fills the width', () => {
    const cols: FitColumn[] = [
      { id: 'text', label: 'Text', min: 200, weight: 1 },
      { id: 'qty', label: 'Qty', min: 120, weight: 1, protect: true },
      { id: 'act', label: 'Actions', min: 40, fixed: 40 },
    ];
    const px = layoutColumns(cols, resolveWeights(cols, {}), 260);
    close(sum(px), 260);
    close(px[1], 120);
    close(px[0], 100);
    expect(px[2]).toBe(40);
  });
});
