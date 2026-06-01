import { useMemo } from 'react';
import { Box, Typography, Alert, CircularProgress } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_PROJECT_PROGRESS_BY_PRODUCT } from '../../graphql/queries';

interface ProgressRow {
  hardwareCategory: string;
  productCode: string;
  requiredQuantity: number;
  orderedQuantity: number;
  receivedQuantity: number;
}

interface ProjectProgressDashboardProps {
  projectId?: string;
}

const columns: GridColDef[] = [
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 140 },
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 160 },
  {
    field: 'requiredQuantity',
    headerName: 'Required',
    flex: 0.6,
    minWidth: 110,
    type: 'number',
    headerAlign: 'right',
    align: 'right',
  },
  {
    field: 'orderedQuantity',
    headerName: 'Ordered',
    flex: 0.6,
    minWidth: 110,
    type: 'number',
    headerAlign: 'right',
    align: 'right',
  },
  {
    field: 'receivedQuantity',
    headerName: 'Received',
    flex: 0.6,
    minWidth: 110,
    type: 'number',
    headerAlign: 'right',
    align: 'right',
  },
];

export default function ProjectProgressDashboard({ projectId }: ProjectProgressDashboardProps) {
  const { data, loading, error } = useQuery<{ projectProgressByProduct: ProgressRow[] }>(
    GET_PROJECT_PROGRESS_BY_PRODUCT,
    {
      variables: { projectId: projectId ?? null },
      fetchPolicy: 'cache-and-network',
    },
  );

  const rows = useMemo(() => {
    const list = data?.projectProgressByProduct ?? [];
    return list.map((r) => ({ id: `${r.hardwareCategory}::${r.productCode}`, ...r }));
  }, [data]);

  return (
    <Box sx={{ mb: 2 }}>
      <Typography variant="subtitle1" sx={{ fontWeight: 600, mb: 1 }}>
        Project Progress by Product
      </Typography>

      {error && <Alert severity="error">Error loading progress: {error.message}</Alert>}

      {!error && loading && !data && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress size={24} />
        </Box>
      )}

      {!error && !loading && rows.length === 0 && (
        <Alert severity="info" variant="outlined">
          No hardware schedule found{projectId ? ' for this project' : ''}.
        </Alert>
      )}

      {rows.length > 0 && (
        <Box sx={{ height: 380, width: '100%' }}>
          <DataGrid
            rows={rows}
            columns={columns}
            density="compact"
            pageSizeOptions={[10, 25, 50, 100]}
            initialState={{ pagination: { paginationModel: { pageSize: 25 } } }}
            disableRowSelectionOnClick
          />
        </Box>
      )}
    </Box>
  );
}
