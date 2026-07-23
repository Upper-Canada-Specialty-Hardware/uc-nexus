import { useState, useMemo, useCallback } from 'react';
import { Box, Typography } from '@mui/material';
import { useQuery } from '@apollo/client/react';
import { GET_MY_WORK } from '../../graphql/shop-assembly';
import { useIdentity } from '../../hooks/useIdentity';
import DataTable from '../../components/DataTable';
import AssemblyDetailModal from './AssemblyDetailModal';
import { leafLabel } from '../../utils/leaf';
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
    field: 'itemCount',
    headerName: 'Hardware Items',
    flex: 1,
    valueGetter: (_value: unknown, row: MyWorkOpening) => row.items?.length ?? 0,
  },
];

export default function MyWorkPage() {
  const { displayName, userId } = useIdentity();
  const [selectedOpening, setSelectedOpening] = useState<MyWorkOpening | null>(null);

  const { data, loading, refetch } = useQuery<{ myWork: MyWorkOpening[] }>(GET_MY_WORK, {
    // Filter on the stable Clerk user id (#324); skip until Clerk has resolved it.
    variables: { assignedToUserId: userId },
    skip: !userId,
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
          completedBy={displayName}
        />
      )}
    </Box>
  );
}
