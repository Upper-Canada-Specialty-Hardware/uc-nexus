import { useCallback, useMemo, useState } from 'react';
import { DataGrid, type GridColDef, type GridColumnResizeParams } from '@mui/x-data-grid';
import type { ClassificationRow } from './types';
import { microLabelSx, monoSx, tabularSx } from '../../theme';

// #733: the row table under a guided classification card and inside every review group. Both used to
// be plain MUI tables, which cannot be resized; this is one DataGrid both render, so a user can drag
// any column edge wider or narrower. Every cell wraps (auto row height, no ellipsis), so a long value
// is always read in full whatever width the column is dragged to.
//
// The hardware category itself arrives from TITAN already cut to 15 characters ("IC Mortise Cyli");
// that is the export, not this grid, and was ruled out of scope in #788.

// Widths a user drags to are remembered in this browser, per column, and shared by both tables since
// they carry the same columns. A convenience only: storage can be missing or refuse writes, and the
// grid then just starts from its default widths.
const WIDTHS_KEY = 'ucnexus.import.classificationColumnWidths';

function readWidths(): Record<string, number> {
  try {
    const raw = localStorage.getItem(WIDTHS_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : null;
    if (!parsed || typeof parsed !== 'object') return {};
    const out: Record<string, number> = {};
    for (const [field, width] of Object.entries(parsed)) {
      if (typeof width === 'number' && Number.isFinite(width) && width > 0) out[field] = width;
    }
    return out;
  } catch {
    return {};
  }
}

function writeWidths(widths: Record<string, number>) {
  try {
    localStorage.setItem(WIDTHS_KEY, JSON.stringify(widths));
  } catch {
    // Storage refused: the width still holds for this session, it just is not remembered.
  }
}

const dash = (value: unknown) => (value ? String(value) : '—');

// Short values get a fixed width sized to their content; Product Code and Category are the long,
// variable ones, so they flex and absorb the slack.
const DATA_COLUMNS: GridColDef<ClassificationRow>[] = [
  { field: 'openingNumber', headerName: 'Opening', width: 100, cellClassName: 'mono-cell' },
  { field: 'hand', headerName: 'Hand', width: 80, valueFormatter: dash },
  { field: 'doorMaterial', headerName: 'Door Material', width: 130, valueFormatter: dash },
  { field: 'frameType', headerName: 'Frame Type', width: 120, valueFormatter: dash },
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 150, cellClassName: 'mono-cell' },
  { field: 'hardwareCategory', headerName: 'Category', flex: 1, minWidth: 140 },
  {
    field: 'itemQuantity',
    headerName: 'Qty',
    type: 'number',
    width: 70,
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
  const [widths, setWidths] = useState<Record<string, number>>(readWidths);

  const columns = useMemo<GridColDef<ClassificationRow>[]>(
    () =>
      [...DATA_COLUMNS, ...classificationColumns].map((col) => {
        const saved = widths[col.field];
        // A dragged width replaces flex: a flex column would otherwise re-spread and undo the drag.
        return saved ? { ...col, width: saved, flex: undefined } : col;
      }),
    [classificationColumns, widths],
  );

  const onColumnWidthChange = useCallback((params: GridColumnResizeParams) => {
    setWidths((prev) => {
      const next = { ...prev, [params.colDef.field]: Math.round(params.width) };
      writeWidths(next);
      return next;
    });
  }, []);

  return (
    <DataGrid
      rows={rows}
      columns={columns}
      onColumnWidthChange={onColumnWidthChange}
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
      sx={{
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
      }}
    />
  );
}
