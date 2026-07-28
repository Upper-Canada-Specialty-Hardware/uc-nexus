import { DataGrid, type GridColDef, type DataGridProps } from '@mui/x-data-grid';
import { Box } from '@mui/material';

interface DataTableProps extends Omit<DataGridProps, 'columns'> {
  columns: GridColDef[];
  height?: number | string;
}

export default function DataTable({ columns, height = 400, sx, ...props }: DataTableProps) {
  // A grid whose rows do something on click has to say so; without an onRowClick the rows stay
  // inert and keep the default cursor.
  const clickable = Boolean(props.onRowClick);

  return (
    <Box sx={{ height, width: '100%' }}>
      <DataGrid
        columns={columns}
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
          // Caller styles win: they land last in the cascade.
          ...(Array.isArray(sx) ? sx : [sx]),
        ]}
        {...props}
      />
    </Box>
  );
}
