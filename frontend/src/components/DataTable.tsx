import { DataGrid, type GridColDef, type DataGridProps } from '@mui/x-data-grid';
import { Box } from '@mui/material';

interface DataTableProps extends Omit<DataGridProps, 'columns'> {
  columns: GridColDef[];
  height?: number | string;
}

export default function DataTable({ columns, height = 400, ...props }: DataTableProps) {
  return (
    <Box sx={{ height, width: '100%' }}>
      <DataGrid
        columns={columns}
        pageSizeOptions={[10, 25, 50]}
        initialState={{
          pagination: { paginationModel: { pageSize: 10 } },
        }}
        disableRowSelectionOnClick
        {...props}
      />
    </Box>
  );
}
