import { act, render } from '@testing-library/react';
import type { GridColDef } from '@mui/x-data-grid';
import DataTable from '../DataTable';

// #909: DataTable hands the grid fitted columns and wires the resize memory, and still passes the
// caller's own props and width-change handler through. The grid itself is stubbed so the test sees
// exactly what DataTable gives it.
const gridProps = vi.hoisted(() => ({ last: null as Record<string, unknown> | null }));
vi.mock('@mui/x-data-grid', () => ({
  DataGrid: (props: Record<string, unknown>) => {
    gridProps.last = props;
    return <div data-testid="grid" />;
  },
}));

const COLUMNS: GridColDef[] = [
  { field: 'name', headerName: 'Name', flex: 1, minWidth: 180 },
  { field: 'qty', headerName: 'Qty', type: 'number', width: 90 },
];

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
});

describe('DataTable', () => {
  it('fits the columns and passes the caller props through', () => {
    render(<DataTable columns={COLUMNS} rows={[]} checkboxSelection storageKey="test.table" />);
    const props = gridProps.last!;
    const cols = props.columns as GridColDef[];
    expect(cols.map((c) => c.flex)).toEqual([1, 0.9]);
    expect(cols[0].minWidth).toBe(180);
    expect(props.checkboxSelection).toBe(true);
    expect(props.storageKey).toBeUndefined();
  });

  it('remembers a resize under its storage key and still calls the caller handler', () => {
    const onColumnWidthChange = vi.fn();
    render(
      <DataTable columns={COLUMNS} rows={[]} storageKey="test.table" onColumnWidthChange={onColumnWidthChange} />,
    );
    const handler = gridProps.last!.onColumnWidthChange as (...args: unknown[]) => void;
    act(() => handler({ colDef: { field: 'name' }, width: 250 }, {}, {}));
    expect(onColumnWidthChange).toHaveBeenCalledTimes(1);
    expect(JSON.parse(localStorage.getItem('uc-nexus:grid-column-widths:test.table')!)).toEqual({ name: 250 });
  });

  // #1283: a clickable row opens from the keyboard - Enter on the focused cell itself.
  describe('Enter on a cell', () => {
    type KeyHandler = (params: unknown, event: unknown, details: unknown) => void;
    const cell = () => {
      const el = document.createElement('div');
      el.setAttribute('role', 'gridcell');
      return el;
    };
    const keyEvent = (key: string, target: HTMLElement) => ({
      key,
      target,
      defaultMuiPrevented: false,
      preventDefault: vi.fn(),
    });
    const params = { id: 'r1', row: { id: 'r1', name: 'x' }, cellMode: 'view', isEditable: false };

    it('opens the row', () => {
      const onRowClick = vi.fn();
      render(<DataTable columns={COLUMNS} rows={[]} onRowClick={onRowClick} />);
      const handler = gridProps.last!.onCellKeyDown as KeyHandler;
      act(() => handler(params, keyEvent('Enter', cell()), {}));
      expect(onRowClick).toHaveBeenCalledTimes(1);
      expect(onRowClick.mock.calls[0][0]).toMatchObject({ id: 'r1', row: { id: 'r1' } });
    });

    it('leaves other keys, inner controls and editing cells alone, and still calls the caller', () => {
      const onRowClick = vi.fn();
      const onCellKeyDown = vi.fn();
      render(<DataTable columns={COLUMNS} rows={[]} onRowClick={onRowClick} onCellKeyDown={onCellKeyDown} />);
      const handler = gridProps.last!.onCellKeyDown as KeyHandler;
      act(() => handler(params, keyEvent('a', cell()), {}));
      act(() => handler(params, keyEvent('Enter', document.createElement('input')), {}));
      act(() => handler({ ...params, cellMode: 'edit' }, keyEvent('Enter', cell()), {}));
      expect(onRowClick).not.toHaveBeenCalled();
      expect(onCellKeyDown).toHaveBeenCalledTimes(3);
    });

    it('does nothing on a grid without onRowClick', () => {
      render(<DataTable columns={COLUMNS} rows={[]} />);
      const handler = gridProps.last!.onCellKeyDown as KeyHandler;
      expect(() => act(() => handler(params, keyEvent('Enter', cell()), {}))).not.toThrow();
    });
  });
});
