import { act, renderHook } from '@testing-library/react';
import type { GridColDef, GridColumnResizeParams } from '@mui/x-data-grid';
import { columnMinWidth, fitGridColumns, useGridColumnFit } from '../useGridColumnFit';

// #909: the DataGrid fit - flex down to each column's minimum, remembered resized widths, and a
// grid whose columns never add up to more than its width.

const KEY = 'uc-nexus:grid-column-widths:test.grid';

const COLUMNS: GridColDef[] = [
  { field: 'name', headerName: 'Name', flex: 2, minWidth: 200 },
  { field: 'qty', headerName: 'Qty', type: 'number', width: 90 },
  { field: 'note', headerName: 'Note' },
  { field: 'actions', headerName: 'Actions', width: 120, resizable: false },
];

const byField = (cols: GridColDef[], field: string) => cols.find((c) => c.field === field)!;

function resize(field: string, width: number): GridColumnResizeParams {
  return { colDef: { field } as GridColDef, width } as unknown as GridColumnResizeParams;
}

/** An in-memory Storage: the runner may expose none, and each test wants its own. */
function memoryStorage(): Storage {
  const items = new Map<string, string>();
  return {
    get length() {
      return items.size;
    },
    clear: () => items.clear(),
    getItem: (key) => items.get(key) ?? null,
    key: (index) => [...items.keys()][index] ?? null,
    removeItem: (key) => void items.delete(key),
    setItem: (key, value) => void items.set(key, String(value)),
  };
}

beforeEach(() => {
  vi.stubGlobal('localStorage', memoryStorage());
});

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('fitGridColumns', () => {
  it('flexes every column down to a minimum, and keeps a fixed column fixed', () => {
    const out = fitGridColumns(COLUMNS, {}, 0);
    expect(byField(out, 'name')).toMatchObject({ flex: 2, minWidth: 200 });
    // A declared width becomes the column's flex share; its floor comes from its type and header.
    expect(byField(out, 'qty')).toMatchObject({ flex: 0.9, minWidth: columnMinWidth(COLUMNS[1]) });
    expect(byField(out, 'qty').width).toBeUndefined();
    expect(byField(out, 'note')).toMatchObject({ flex: 1, minWidth: 100 });
    expect(byField(out, 'actions')).toMatchObject({ width: 120 });
    expect(byField(out, 'actions').flex).toBeUndefined();
  });

  it('gives a column with no minWidth one that fits its type and header', () => {
    expect(columnMinWidth({ field: 'n', headerName: 'N', type: 'number' })).toBe(80);
    expect(columnMinWidth({ field: 'd', headerName: 'D', type: 'dateTime' })).toBe(160);
    expect(columnMinWidth({ field: 'x', headerName: 'Supplier reference number' })).toBeGreaterThan(200);
    expect(columnMinWidth({ field: 'x', minWidth: 42 })).toBe(42);
  });

  it('holds a resized column at its stored width while the others keep flexing', () => {
    const out = fitGridColumns(COLUMNS, { note: 260 }, 1200);
    expect(byField(out, 'note')).toMatchObject({ flex: 0, width: 260 });
    expect(byField(out, 'name').flex).toBe(2);
  });

  it('never lets a stored width go under the column minimum', () => {
    const out = fitGridColumns(COLUMNS, { name: 50 }, 1200);
    expect(byField(out, 'name')).toMatchObject({ flex: 0, width: 200 });
  });

  it('caps each resizable column at what the others can spare, so a drag stops at the edge', () => {
    const width = 1000;
    const out = fitGridColumns(COLUMNS, {}, width);
    const avail = width - 18;
    const otherMins = 200 + 100 + 120; // name, note, actions
    expect(byField(out, 'qty').maxWidth).toBe(avail - otherMins);
  });

  it('gives back from resized columns first when the grid is too narrow for them', () => {
    const width = 700;
    const out = fitGridColumns(COLUMNS, { note: 600 }, width);
    const total = out.reduce((a, c) => a + (c.flex ? (c.minWidth ?? 0) : (c.width ?? 0)), 0);
    expect(total).toBeLessThanOrEqual(width - 18);
    expect(byField(out, 'note').width).toBeGreaterThanOrEqual(100);
    expect(byField(out, 'name').minWidth).toBe(200);
  });

  it('scales every column down in proportion when even the minimums do not fit', () => {
    const width = 300;
    const out = fitGridColumns(COLUMNS, {}, width);
    const total = out.reduce((a, c) => a + (c.flex ? (c.minWidth ?? 0) : (c.width ?? 0)), 0);
    expect(total).toBeLessThanOrEqual(width - 18);
    expect(byField(out, 'name').minWidth).toBeLessThan(200);
  });

  it('flexes by the stored widths once every column has been resized, so the grid still fills', () => {
    const out = fitGridColumns(COLUMNS, { name: 300, qty: 100, note: 200 }, 1200);
    expect(byField(out, 'name')).toMatchObject({ flex: 300 });
    expect(byField(out, 'note')).toMatchObject({ flex: 200 });
  });

  it('leaves room for the checkbox column and ignores hidden columns', () => {
    const width = 1000;
    const out = fitGridColumns(COLUMNS, {}, width, { checkboxSelection: true, columnVisibilityModel: { note: false } });
    expect(byField(out, 'qty').maxWidth).toBe(width - 18 - 50 - (200 + 120));
  });
});

describe('useGridColumnFit', () => {
  it('restores a width the person set on an earlier visit', () => {
    localStorage.setItem(KEY, JSON.stringify({ note: 240 }));
    const { result } = renderHook(() => useGridColumnFit('test.grid', COLUMNS));
    expect(byField(result.current.gridProps.columns, 'note')).toMatchObject({ flex: 0, width: 240 });
  });

  it('remembers a resize, merged into what was stored', () => {
    localStorage.setItem(KEY, JSON.stringify({ gone: 99 }));
    const { result } = renderHook(() => useGridColumnFit('test.grid', COLUMNS));
    act(() => result.current.gridProps.onColumnWidthChange(resize('name', 333.4)));
    expect(byField(result.current.gridProps.columns, 'name')).toMatchObject({ flex: 0, width: 333 });
    expect(JSON.parse(localStorage.getItem(KEY)!)).toEqual({ gone: 99, name: 333 });
  });

  it('keeps a resize for the visit only without a storage key', () => {
    const { result } = renderHook(() => useGridColumnFit(null, COLUMNS));
    act(() => result.current.gridProps.onColumnWidthChange(resize('name', 300)));
    expect(byField(result.current.gridProps.columns, 'name').width).toBe(300);
    expect(localStorage.length).toBe(0);
  });

  it('shrugs off storage that throws', () => {
    const blocked = () => {
      throw new Error('blocked');
    };
    vi.stubGlobal('localStorage', { getItem: blocked, setItem: blocked });
    const { result } = renderHook(() => useGridColumnFit('test.grid', COLUMNS));
    expect(byField(result.current.gridProps.columns, 'name').flex).toBe(2);
    act(() => result.current.gridProps.onColumnWidthChange(resize('name', 300)));
    expect(byField(result.current.gridProps.columns, 'name').width).toBe(300);
  });

  it('hands the grid the guard that hides its horizontal scrollbar', () => {
    const { result } = renderHook(() => useGridColumnFit('test.grid', COLUMNS));
    expect(result.current.gridProps.sx).toHaveProperty('& .MuiDataGrid-scrollbar--horizontal');
  });
});
