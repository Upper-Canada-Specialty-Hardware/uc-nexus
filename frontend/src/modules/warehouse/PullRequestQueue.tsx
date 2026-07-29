import { useMemo, useState } from 'react';
import { Alert, Box, Typography, Chip, Stack } from '@mui/material';
import { ChevronRight } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PULL_REQUESTS } from '../../graphql/warehouse';
import DataTable from '../../components/DataTable';
import Tabs from '../../components/Tabs';
import PullRequestDetailModal from './PullRequestDetailModal';
import { pullPhase } from './pullStaging';
import { monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

// --- Types ---

export interface PullRequestItem {
  id: string;
  pullRequestId: string;
  itemType: string;
  openingNumber: string;
  openingItemId: string | null;
  /** Door leaf this pull line is for (#311): 1 or 2, or null for legacy / leaf-agnostic lines. */
  leaf: number | null;
  hardwareCategory: string | null;
  productCode: string | null;
  requestedQuantity: number;
  /** Fetch check-off on an OPENING_ITEM line (#367). Always null on a LOOSE line. */
  fetchedAt?: string | null;
  fetchedBy?: string | null;
}

export interface PullRequest {
  id: string;
  requestNumber: string;
  projectId: string;
  source: string;
  status: string;
  requestedBy: string;
  assignedTo: string | null;
  createdAt: string;
  updatedAt: string;
  approvedAt: string | null;
  completedAt: string | null;
  cancelledAt: string | null;
  cancelledBy: string | null;
  cancellationReason: string | null;
  /** Derived per-opening staging rollup (#343): NOT_PULLED / PARTIAL / PULLED over this pull's
   *  shop-assembly openings. Null when the pull has none (shipping-out, PR-REPL, legacy). */
  stagingStatus: string | null;
  stagedOpeningCount: number | null;
  totalOpeningCount: number | null;
  /** When the pick was confirmed and by whom (#367) - the moment stock left inventory. */
  pickedAt: string | null;
  pickedBy: string | null;
  /** Stock is off the shelf for this pull but it is not fully picked: a short confirm is
   *  outstanding. Only computed for un-picked pulls; null means "not evaluated". */
  partiallyPicked: boolean | null;
  items: PullRequestItem[];
}

// --- Status config ---

const STATUS_CHIP_COLOR: Record<string, 'warning' | 'info' | 'success' | 'error' | 'default'> = {
  PENDING: 'warning',
  IN_PROGRESS: 'info',
  COMPLETED: 'success',
  CANCELLED: 'error',
};

function formatStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return parseServerDate(dateStr).toLocaleDateString();
}

// --- Columns ---

const columns: GridColDef[] = [
  {
    field: 'requestNumber',
    headerName: 'Request #',
    flex: 1,
    minWidth: 140,
    renderCell: (params) => (
      <Typography component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.value as string}
      </Typography>
    ),
  },
  {
    field: 'createdAt',
    headerName: 'Created Date',
    flex: 1,
    minWidth: 140,
    valueGetter: (_value: unknown, row: PullRequest) => formatDate(row.createdAt),
  },
  {
    field: 'requestedBy',
    headerName: 'Requested By',
    flex: 1,
    minWidth: 140,
  },
  {
    field: 'itemsCount',
    headerName: 'Items',
    flex: 0.8,
    minWidth: 120,
    type: 'number',
    valueGetter: (_value: unknown, row: PullRequest) => row.items?.length ?? 0,
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 1,
    minWidth: 130,
    renderCell: (params) => (
      <Chip
        label={formatStatus(params.value as string)}
        color={STATUS_CHIP_COLOR[params.value as string] ?? 'default'}
        size="small"
      />
    ),
  },
  {
    // Where the pull actually is (#367). Status alone stopped being enough once picking became its
    // own phase: In Progress now covers "nothing off the shelf yet", "part-picked and short", and
    // "picked, staging carts", which mean completely different things to whoever takes the row next.
    field: 'phase',
    headerName: 'Phase',
    flex: 1.2,
    minWidth: 180,
    sortable: false,
    valueGetter: (_value: unknown, row: PullRequest) => pullPhase(row).label,
    renderCell: (params) => {
      const phase = pullPhase(params.row as PullRequest);
      return (
        <Stack spacing={0.25} sx={{ py: 0.5 }}>
          <Box>
            <Chip label={phase.label} color={phase.color} size="small" />
          </Box>
          {phase.detail && (
            <Typography variant="caption" color="text.secondary" sx={tabularSx}>
              {phase.detail}
            </Typography>
          )}
        </Stack>
      );
    },
  },
  {
    // The whole row opens the pull; the chevron is what tells the user so.
    field: 'open',
    headerName: '',
    width: 44,
    sortable: false,
    filterable: false,
    align: 'center',
    renderCell: () => (
      <Box data-row-open aria-hidden sx={{ display: 'flex', color: 'text.secondary' }}>
        <ChevronRight size={18} strokeWidth={1.75} />
      </Box>
    ),
  },
];

// --- Tab content component ---

interface PullRequestTabProps {
  source: string;
}

function PullRequestTab({ source }: PullRequestTabProps) {
  // The id, not the row (#343). The modal stages openings and cancels the pull, both of which
  // refetch this list; holding the object would pin the modal's staging chip to the pre-staging
  // snapshot - the same trap #340 fixed in the assembly views.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, loading, error } = useQuery<{ pullRequests: PullRequest[] }>(GET_PULL_REQUESTS, {
    variables: { source },
  });

  const requests = useMemo(() => data?.pullRequests ?? [], [data]);
  const selected = useMemo(() => requests.find((pr) => pr.id === selectedId) ?? null, [requests, selectedId]);

  const handleRowClick = (params: GridRowParams<PullRequest>) => {
    setSelectedId(params.row.id);
  };

  return (
    <>
      {/* Without this, a failed load reads as an empty queue - the one thing this screen must
          never claim wrongly. */}
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          Error loading pull requests: {error.message}
        </Alert>
      )}
      <DataTable
        columns={columns}
        rows={requests}
        loading={loading}
        onRowClick={handleRowClick}
        // The phase cell is a tag over a line of detail (#367); the default 52px row clips it.
        rowHeight={64}
        height={520}
        localeText={{ noRowsLabel: 'No pull requests' }}
        sx={{
          cursor: 'pointer',
          '& .MuiDataGrid-row:hover [data-row-open]': { color: 'text.primary' },
        }}
        getRowId={(row) => row.id}
      />
      {selected && (
        <PullRequestDetailModal
          open
          pr={selected}
          onClose={() => setSelectedId(null)}
          onRefetch={() => setSelectedId(null)}
        />
      )}
    </>
  );
}

// --- Main component ---

export default function PullRequestQueue() {
  const tabs = [
    { label: 'Shop Assembly', content: <PullRequestTab source="SHOP_ASSEMBLY" /> },
    { label: 'Shipping Out', content: <PullRequestTab source="SHIPPING_OUT" /> },
  ];

  return (
    <Box>
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Pull Request Queue
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 1.5 }}>
        Every request to take hardware out of inventory. Open a row to start its pick, stage the
        carts and complete it.
      </Typography>

      <Tabs tabs={tabs} defaultTab={0} />
    </Box>
  );
}
