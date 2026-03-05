import { useMemo } from 'react';
import { Box, CircularProgress, Alert } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import type { GridColDef } from '@mui/x-data-grid';
import { GET_HARDWARE_SUMMARY } from '../../graphql/queries';
import { useProject } from '../../contexts/ProjectContext';
import DataTable from '../../components/DataTable';

interface HardwareSummaryRow {
  hardwareCategory: string;
  productCode: string;
  poDrafted: number;
  ordered: number;
  received: number;
  backOrdered: number;
  shippedOut: number;
}

const columns: GridColDef[] = [
  { field: 'hardwareCategory', headerName: 'Hardware Category', flex: 1, minWidth: 160 },
  { field: 'productCode', headerName: 'Product Code', flex: 1, minWidth: 140 },
  { field: 'poDrafted', headerName: 'PO Drafted', type: 'number', width: 110 },
  { field: 'ordered', headerName: 'Ordered', type: 'number', width: 100 },
  { field: 'received', headerName: 'Received', type: 'number', width: 100 },
  { field: 'backOrdered', headerName: 'Back-Ordered', type: 'number', width: 120 },
  { field: 'shippedOut', headerName: 'Shipped Out', type: 'number', width: 110 },
];

export default function HardwareSummaryTab() {
  const { project } = useProject();

  const { data, loading, error } = useQuery<{ hardwareSummary: HardwareSummaryRow[] }>(
    GET_HARDWARE_SUMMARY,
    {
      variables: { projectId: project?.id },
      skip: !project,
    },
  );

  const rows = useMemo(
    () =>
      (data?.hardwareSummary ?? []).map((row, idx) => ({
        id: idx,
        ...row,
      })),
    [data],
  );

  if (!project) {
    return <Alert severity="info">Select a project first</Alert>;
  }

  if (loading) {
    return (
      <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
        <CircularProgress />
      </Box>
    );
  }

  if (error) {
    return <Alert severity="error">Error loading hardware summary: {error.message}</Alert>;
  }

  if (rows.length === 0) {
    return <Alert severity="info">No hardware data for this project</Alert>;
  }

  return (
    <DataTable
      columns={columns}
      rows={rows}
      height={600}
      getRowId={(row) => row.id}
    />
  );
}
