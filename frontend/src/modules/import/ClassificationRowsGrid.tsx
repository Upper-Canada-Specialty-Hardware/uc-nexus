import { useMemo } from 'react';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import type { ClassificationRow } from './types';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { useGridColumnFit } from '../../components/useGridColumnFit';

// #733: the row table under a guided classification card and inside every review group. Both used to
// be plain MUI tables, which cannot be resized; this is one DataGrid both render, so a user can drag
// any column edge wider or narrower. Every cell wraps (auto row height, no ellipsis), so a long value
// is always read in full whatever width the column is dragged to.
//
// The hardware category itself arrives from TITAN already cut to 15 characters ("IC Mortise Cyli");
// that is the export, not this grid, and was ruled out of scope in #788.

// #909: the columns fit the grid's width and never scroll sideways. Widths a person drags to are
// remembered per person under one key shared by both tables, since they carry the same columns.
const CLASSIFICATION_ROWS_STORAGE_KEY = 'import.classification.rows';

const dash = (value: unknown) => (value ? String(value) : '—');

// Short values get a narrow share sized to their content; Product Code and Category are the long,
// variable ones, so they take the larger share of the slack.
const DATA_COLUMNS: GridColDef<ClassificationRow>[] = [
  { field: 'openingNumber', headerName: 'Opening', width: 100, minWidth: 90, cellClassName: 'mono-cell' },
  { field: 'hand', headerName: 'Hand', width: 80, minWidth: 64, valueFormatter: dash },
  { field: 'doorMaterial', headerName: 'Door Material', width: 130, minWidth: 110, valueFormatter: dash },
  { field: 'frameType', headerName: 'Frame Type', width: 120, minWidth: 100, valueFormatter: dash },
  { field: 'productCode', headerName: 'Product Code', flex: 1.5, minWidth: 150, cellClassName: 'mono-cell' },
  { field: 'hardwareCategory', headerName: 'Category', flex: 1.5, minWidth: 140 },
  {
    field: 'itemQuantity',
    headerName: 'Qty',
    type: 'number',
    width: 70,
    minWidth: 60,
    cellClassName: 'figure-cell',
  },
];

// The MIT DataGrid always paginates and caps a page at 100 rows. A group of up to 100 lines shows
// whole with no footer; a larger one keeps the paginator so no line is ever silently dropped.
const PAGE_SIZE = 100;

interface ClassificationRowsGridProps {
  rows: ClassificationRow[];
  /** The classification cells after the data columns: chips on a guided card, toggles in review. */
  classificationColumns: GridColDef<ClassificationRow>[];
}

export default function ClassificationRowsGrid({ rows, classificationColumns }: ClassificationRowsGridProps) {
  const columns = useMemo<GridColDef<ClassificationRow>[]>(
    () => [
      ...DATA_COLUMNS,
      // The classification cells hold chips or toggle buttons: their declared width is the least
      // that keeps the control whole.
      ...classificationColumns.map((col) =>
        col.minWidth === undefined && col.width ? { ...col, minWidth: col.width } : col,
      ),
    ],
    [classificationColumns],
  );
  const { setContainer, gridProps: fit } = useGridColumnFit(CLASSIFICATION_ROWS_STORAGE_KEY, columns);

  return (
    <DataGrid
      ref={setContainer}
      {...fit}
      rows={rows}
      density="compact"
      getRowHeight={() => 'auto'}
      autoHeight
      // A group is at most a page of rows, and every row's toggles must be in the DOM to be reachable.
      disableVirtualization
      disableRowSelectionOnClick
      disableColumnMenu
      hideFooter={rows.length <= PAGE_SIZE}
      pageSizeOptions={[PAGE_SIZE]}
      initialState={{ pagination: { paginationModel: { pageSize: PAGE_SIZE } } }}
      sx={[
        fit.sx,
        {
          border: 0,
          '& .MuiDataGrid-columnHeaderTitle': microLabelSx,
          // Wrap, never ellipsize: the full value is always readable at any column width.
          '& .MuiDataGrid-cell': {
            whiteSpace: 'normal',
            wordBreak: 'break-word',
            lineHeight: 1.43,
            py: 0.75,
            display: 'flex',
            alignItems: 'center',
          },
          '& .MuiDataGrid-cell--textRight': { justifyContent: 'flex-end' },
          '& .mono-cell': monoSx,
          '& .figure-cell': tabularSx,
        },
      ]}
    />
  );
}
