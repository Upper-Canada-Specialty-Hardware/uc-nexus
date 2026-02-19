import { useState, useMemo, useCallback } from 'react';
import { Box, Typography, Alert } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_MY_WORK } from '../../graphql/queries';
import { useProject } from '../../contexts/ProjectContext';
import { useRole } from '../../contexts/RoleContext';
import DataTable from '../../components/DataTable';
import AssemblyDetailModal from './AssemblyDetailModal';
import type { GridColDef } from '@mui/x-data-grid';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
}

interface MyWorkOpening {
  id: string;
  shopAssemblyRequestId: string;
  openingId: string;
  pullStatus: string;
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  items: OpeningItem[];
}

const columns: GridColDef[] = [
  { field: 'openingNumber', headerName: 'Opening Number', flex: 1 },
  { field: 'building', headerName: 'Building', flex: 1 },
  { field: 'floor', headerName: 'Floor', flex: 1 },
  {
    field: 'itemCount',
    headerName: 'Hardware Items',
    flex: 1,
    valueGetter: (value: unknown, row: MyWorkOpening) => row.items?.length ?? 0,
  },
];

export default function MyWorkPage() {
  const { project } = useProject();
  const { role } = useRole();
  const [selectedOpening, setSelectedOpening] = useState<MyWorkOpening | null>(null);

  const assignedTo = role || 'Shop Assembly User';

  const { data, loading, refetch } = useQuery<{ myWork: MyWorkOpening[] }>(GET_MY_WORK, {
    variables: { assignedTo },
    skip: !role,
    pollInterval: 10000,
  });

  const rows = useMemo(() => data?.myWork ?? [], [data]);

  const handleRowClick = useCallback(
    (params: { row: MyWorkOpening }) => {
      setSelectedOpening(params.row);
    },
    []
  );

  const handleCompleted = useCallback(() => {
    setSelectedOpening(null);
    refetch();
  }, [refetch]);

  if (!project) {
    return (
      <Box sx={{ p: 4 }}>
        <Alert severity='info'>Please select a project to view your work.</Alert>
      </Box>
    );
  }

  return (
    <Box>
      <Typography variant='h5' gutterBottom>
        My Work
      </Typography>

      <DataTable
        rows={rows}
        columns={columns}
        loading={loading}
        onRowClick={handleRowClick}
        getRowId={(row: MyWorkOpening) => row.id}
      />

      {selectedOpening && (
        <AssemblyDetailModal
          open={!!selectedOpening}
          opening={selectedOpening}
          onClose={() => setSelectedOpening(null)}
          onCompleted={handleCompleted}
        />
      )}
    </Box>
  );
}
