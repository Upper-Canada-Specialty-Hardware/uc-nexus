import { useState, useMemo, useCallback } from 'react';
import { Box, Typography, Chip, LinearProgress } from '@mui/material';
import { ChevronRight } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import { GET_MY_WORK } from '../../graphql/shop-assembly';
import { useIdentity } from '../../hooks/useIdentity';
import DataTable from '../../components/DataTable';
import AssemblyDetailModal from './AssemblyDetailModal';
import ReplacementWorkPanel from './ReplacementWorkPanel';
import { assemblyProgress, assemblyStatusLabel, unitProgressLabel } from './openingFilters';
import { leafLabel } from '../../utils/leaf';
import { monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import type { GridColDef } from '@mui/x-data-grid';

interface OpeningItem {
  id: string;
  shopAssemblyOpeningId: string;
  hardwareCategory: string;
  productCode: string;
  // Owed by the schedule vs pulled for the bench. The three progress buckets partition
  // `allocatedQuantity`; `quantity - allocatedQuantity` was never pulled and is not outstanding work.
  quantity: number;
  allocatedQuantity: number;
  installedQuantity: number;
  deficientQuantity: number;
  // Arrived-but-not-yet-fitted replacement units (#341): the third bucket a line is partitioned
  // into, and part of the progress rollup's `remaining`.
  replacementPendingQuantity: number;
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

// Widths, not flex: these are two-character values and short refs, and a flexed grid stretched them
// across 250px of empty column each. Every column is sized to what it actually holds.
const columns: GridColDef[] = [
  {
    field: 'openingNumber',
    headerName: 'Opening',
    width: 130,
    renderCell: (params) => (
      <Box component="span" sx={monoSx}>
        {params.row.openingNumber ?? '-'}
      </Box>
    ),
  },
  {
    field: 'leaf',
    headerName: 'Leaf',
    width: 84,
    valueGetter: (_value: unknown, row: MyWorkOpening) => leafLabel(row.leaf) ?? '-',
  },
  { field: 'building', headerName: 'Building', width: 110 },
  { field: 'floor', headerName: 'Floor', width: 84 },
  {
    field: 'assemblyStatus',
    headerName: 'Status',
    width: 128,
    // Assembly status is real system state, so it earns a status chip. In Progress is the one that
    // matters here: it says the leaf has saved work on it and can be picked straight back up (#340).
    renderCell: (params) => (
      <Chip
        size='small'
        label={assemblyStatusLabel(params.row.assemblyStatus)}
        color={params.row.assemblyStatus === 'IN_PROGRESS' ? 'info' : 'default'}
      />
    ),
  },
  {
    field: 'progress',
    headerName: 'Progress',
    width: 190,
    // Units, not lines: a line of 8 hinges with 5 fitted is most of the job, and a line count would
    // report it as untouched.
    valueGetter: (_value: unknown, row: MyWorkOpening) => {
      // Accounted-for is planned minus remaining, so the three buckets a line is partitioned into
      // (installed, condemned, replacement arrived but not yet fitted) all count - a finished leaf
      // never reads as 3/4 because its replacement turned up.
      return unitProgressLabel(row.items ?? []);
    },
    renderCell: (params) => {
      const items = (params.row as MyWorkOpening).items ?? [];
      const { dispositioned, allocated } = assemblyProgress(items);
      const pct = allocated > 0 ? (dispositioned / allocated) * 100 : 0;
      return (
        <Box sx={{ width: '100%', display: 'flex', flexDirection: 'column', gap: 0.5, py: 1 }}>
          <Typography variant='caption' color='text.secondary' sx={tabularSx}>
            {unitProgressLabel(items)}
          </Typography>
          {/* The bar transitions to its value on mount and on every refetch, so a save reads as
              movement rather than as a number that quietly changed. */}
          <LinearProgress
            variant='determinate'
            value={pct}
            color={pct >= 100 ? 'success' : 'primary'}
            sx={{ height: 4, '& .MuiLinearProgress-bar': { transition: 'transform 0.45s ease' } }}
          />
        </Box>
      );
    },
  },
  {
    field: 'itemCount',
    headerName: 'Lines',
    width: 84,
    align: 'right',
    headerAlign: 'right',
    valueGetter: (_value: unknown, row: MyWorkOpening) => row.items?.length ?? 0,
  },
  {
    // The row is the click target; the chevron says so.
    field: 'open',
    headerName: '',
    width: 44,
    sortable: false,
    filterable: false,
    disableColumnMenu: true,
    align: 'right',
    renderCell: () => (
      <Box sx={{ color: 'text.disabled', display: 'flex', alignItems: 'center', height: '100%' }}>
        <ChevronRight size={18} strokeWidth={1.75} />
      </Box>
    ),
  },
];

export default function MyWorkPage() {
  const { userId } = useIdentity();
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
      <FadeIn>
        <Typography variant='h5' sx={{ mb: 0.5 }}>
          My Work
        </Typography>
        <Typography variant='body2' color='text.secondary' sx={{ mb: 2 }}>
          Door leaves assigned to you. Open one to record what you have fitted.
        </Typography>
      </FadeIn>

      <FadeIn delay={0.08}>
        <DataTable
          rows={rows}
          columns={columns}
          loading={loading}
          onRowClick={handleRowClick}
          getRowId={(row: MyWorkOpening) => row.id}
          rowHeight={56}
        />
      </FadeIn>

      {/* Leaves this assembler already finished that are owed replacement hardware (#341). Kept out
          of the grid above because those rows are unfinished openings and these are complete ones -
          folding them in would mean either reopening a finished work unit or mislabelling it. */}
      <ReplacementWorkPanel assignedToUserId={userId} />

      {selectedOpening && (
        <AssemblyDetailModal
          // Keyed on the leaf so switching openings remounts and re-seeds the draft counts from the
          // newly-selected opening's stored progress.
          key={selectedOpening.id}
          open={!!selectedOpening}
          opening={selectedOpening}
          onClose={() => setSelectedOpeningId(null)}
          onCompleted={handleCompleted}
        />
      )}
    </Box>
  );
}
