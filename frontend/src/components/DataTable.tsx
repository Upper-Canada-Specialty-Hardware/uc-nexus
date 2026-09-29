import { DataGrid, type GridColDef, type DataGridProps } from '@mui/x-data-grid';
import { Box } from '@mui/material';
import { useGridColumnFit } from './useGridColumnFit';

interface DataTableProps extends Omit<DataGridProps, 'columns'> {
  columns: GridColDef[];
  height?: number | string;
  /** #856: grow with the rows up to this height, then scroll inside the grid. Replaces `height` when
   *  set, so a queue with one or two rows is not a mostly empty box. */
  maxHeight?: number | string;
  /** #909: the key a person's resized column widths are remembered under (one per grid). Without
   *  one the grid still fits its width and resizes, but widths last only for the visit. */
  storageKey?: string;
}

export default function DataTable({
  columns,
  height = 400,
  maxHeight,
  storageKey,
  sx,
  onColumnWidthChange,
  ...props
}: DataTableProps) {
  // #909: the columns fit the grid's width (flex down to each column's minimum) and never scroll
  // sideways; a person resizes them with the grid's own header-edge drag, remembered per grid.
  const { setContainer, gridProps: fit } = useGridColumnFit(storageKey ?? null, columns, {
    checkboxSelection: props.checkboxSelection,
    columnVisibilityModel: props.columnVisibilityModel ?? props.initialState?.columns?.columnVisibilityModel,
  });

  // A grid whose rows do something on click has to say so; without an onRowClick the rows stay
  // inert and keep the default cursor.
  const clickable = Boolean(props.onRowClick);

  return (
    <Box
      data-grid-sizing={maxHeight !== undefined ? 'fit-rows' : 'fixed'}
      // #856: the DataGrid's flex-parent layout - a column flex box with only a max height lets the
      // grid size to its rows and scroll its own body past the cap.
      sx={
        maxHeight !== undefined
          ? { display: 'flex', flexDirection: 'column', maxHeight, width: '100%', minWidth: 0 }
          : { height, width: '100%' }
      }
    >
      <DataGrid
        ref={setContainer}
        columns={fit.columns}
        onColumnWidthChange={(params, event, details) => {
          fit.onColumnWidthChange(params);
          onColumnWidthChange?.(params, event, details);
        }}
        pageSizeOptions={[10, 25, 50]}
        initialState={{
          pagination: { paginationModel: { pageSize: 10 } },
        }}
        disableRowSelectionOnClick
        sx={[
          {
            border: 1,
            borderColor: 'divider',
            '& .MuiDataGrid-columnHeaderTitle': {
              fontSize: '0.6875rem',
              fontWeight: 700,
              letterSpacing: '0.08em',
              textTransform: 'uppercase',
            },
            '& .MuiDataGrid-cell': { fontVariantNumeric: 'tabular-nums' },
          },
          clickable && { '& .MuiDataGrid-row': { cursor: 'pointer' } },
          fit.sx,
          // Caller styles win: they land last in the cascade.
          ...(Array.isArray(sx) ? sx : [sx]),
        ]}
        {...props}
      />
    </Box>
  );
}
