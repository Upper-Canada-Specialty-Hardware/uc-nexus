import type { DataGridProps, GridColDef } from '@mui/x-data-grid';

type CellKeyDown = NonNullable<DataGridProps['onCellKeyDown']>;
type RowClick = NonNullable<DataGridProps['onRowClick']>;

/**
 * The grid fires onRowClick for a pointer only, so a row that opens something was mouse-only (#1283). This
 * makes Enter on a focused cell open it too - only on the cell itself, never from a control inside it (an
 * input's Enter is its own), and never on a cell being edited. DataTable applies it; a page with its own
 * DataGrid passes it as `onCellKeyDown` (#1547).
 */
export function openRowOnEnter(onRowClick: RowClick | undefined, columns: GridColDef[]): CellKeyDown {
  return (params, event, details) => {
    if (!onRowClick || event.defaultMuiPrevented || event.key !== 'Enter') return;
    if (params.cellMode !== 'view' || params.isEditable) return;
    if ((event.target as HTMLElement).getAttribute('role') !== 'gridcell') return;
    event.preventDefault();
    onRowClick({ id: params.id, row: params.row, columns }, event as unknown as Parameters<RowClick>[1], details);
  };
}
