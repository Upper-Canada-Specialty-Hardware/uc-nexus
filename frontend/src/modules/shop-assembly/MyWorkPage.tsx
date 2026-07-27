import { useState, useMemo, useCallback } from 'react';
import { Box, Typography, Chip } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_MY_WORK } from '../../graphql/shop-assembly';
import { useIdentity } from '../../hooks/useIdentity';
import DataTable from '../../components/DataTable';
import AssemblyDetailModal from './AssemblyDetailModal';
import { assemblyProgress, assemblyStatusLabel } from './openingFilters';
import { leafLabel } from '../../utils/leaf';
import type { GridColDef } from '@mui/x-data-grid';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  quantity: number;
  installedQuantity: number;
  deficientQuantity: number;
}

interface MyWorkOpening {
  id: string;
  shopAssemblyRequestId: string;
  openingId: string;
  pullStatus: string;
  assignedToUserId: string | null;
  assignedTo: string | null;
  assemblyStatus: string;
  completedAt: string | null;
  openingNumber: string | null;
  building: string | null;
  floor: string | null;
  leaf: number | null;
  items: OpeningItem[];
}

const columns: GridColDef[] = [
  { field: 'openingNumber', headerName: 'Opening Number', flex: 1 },
  {
    field: 'leaf',
    headerName: 'Leaf',
    flex: 0.6,
    valueGetter: (_value: unknown, row: MyWorkOpening) => leafLabel(row.leaf) ?? '-',
  },
  { field: 'building', headerName: 'Building', flex: 1 },
  { field: 'floor', headerName: 'Floor', flex: 1 },
  {
    field: 'assemblyStatus',
    headerName: 'Status',
    flex: 0.9,
    // Assembly status is real system state, so it earns a status chip. In Progress is the one that
    // matters here: it says the leaf has saved work on it and can be picked straight back up (#340).
    renderCell: (params) => (
      <Chip
        size='small'
        variant='outlined'
        label={assemblyStatusLabel(params.row.assemblyStatus)}
        color={params.row.assemblyStatus === 'IN_PROGRESS' ? 'info' : 'default'}
      />
    ),
  },
  {
    field: 'progress',
    headerName: 'Progress',
    flex: 0.9,
    // Units, not lines: a line of 8 hinges with 5 fitted is most of the job, and a line count would
    // report it as untouched.
    valueGetter: (_value: unknown, row: MyWorkOpening) => {
      const { installed, deficient, planned } = assemblyProgress(row.items ?? []);
      return `${installed + deficient}/${planned} units`;
    },
  },
  {
    field: 'itemCount',
    headerName: 'Hardware Items',
    flex: 0.8,
    valueGetter: (_value: unknown, row: MyWorkOpening) => row.items?.length ?? 0,
  },
];

export default function MyWorkPage() {
  const { displayName, userId } = useIdentity();
  // Hold the id, not the row. The modal writes progress and the list refetches; keeping the object
  // would pin the modal to a snapshot taken before the save, so a just-flagged deficiency would not
  // appear in it.
  const [selectedOpeningId, setSelectedOpeningId] = useState<string | null>(null);

  const { data, loading, refetch } = useQuery<{ myWork: MyWorkOpening[] }>(GET_MY_WORK, {
    // Filter on the stable Clerk user id (#324); skip until Clerk has resolved it.
    variables: { assignedToUserId: userId },
    skip: !userId,
  });

  const rows = useMemo(() => data?.myWork ?? [], [data]);
  const selectedOpening = useMemo(
    () => rows.find((r) => r.id === selectedOpeningId) ?? null,
    [rows, selectedOpeningId]
  );

  const handleRowClick = useCallback((params: { row: MyWorkOpening }) => {
    setSelectedOpeningId(params.row.id);
  }, []);

  const handleCompleted = useCallback(() => {
    setSelectedOpeningId(null);
    refetch();
  }, [refetch]);

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
          // Keyed on the leaf so switching openings remounts and re-seeds the draft counts from the
          // newly-selected opening's stored progress.
          key={selectedOpening.id}
          open={!!selectedOpening}
          opening={selectedOpening}
          onClose={() => setSelectedOpeningId(null)}
          onCompleted={handleCompleted}
          completedBy={displayName}
        />
      )}
    </Box>
  );
}
