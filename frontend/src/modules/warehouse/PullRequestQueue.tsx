import { useMemo, useState } from 'react';
import { Alert, Box, Button, Typography, Chip, Stack } from '@mui/material';
import { Link as RouterLink } from 'react-router-dom';
import { ChevronRight, History } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PULL_REQUESTS } from '../../graphql/warehouse';
import DataTable from '../../components/DataTable';
import PullRequestDetailModal from './PullRequestDetailModal';
import { pullPhase } from './pullPhase';
import { monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

// --- Types ---

export interface PullRequestItem {
  id: string;
  pullRequestId: string;
  /** Null on a line whose request was raised straight off inventory (#451). */
  openingNumber: string | null;
  hardwareCategory: string;
  productCode: string;
  requestedQuantity: number;
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

// Trimmed to the five that keep each half dense once the queues sit side by side: the created date
// no longer earns its own column and rides in the phase detail line instead (see below).
const columns: GridColDef[] = [
  {
    field: 'requestNumber',
    headerName: 'Request #',
    flex: 1,
    minWidth: 120,
    renderCell: (params) => (
      <Typography component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.value as string}
      </Typography>
    ),
  },
  {
    field: 'requestedBy',
    headerName: 'Requested By',
    flex: 1,
    minWidth: 120,
  },
  {
    field: 'itemsCount',
    headerName: 'Items',
    flex: 0.6,
    minWidth: 80,
    type: 'number',
    valueGetter: (_value: unknown, row: PullRequest) => row.items?.length ?? 0,
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 0.9,
    minWidth: 110,
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
    flex: 1.4,
    minWidth: 180,
    sortable: false,
    valueGetter: (_value: unknown, row: PullRequest) => pullPhase(row).label,
    renderCell: (params) => {
      const row = params.row as PullRequest;
      const phase = pullPhase(row);
      // The created date rode in its own column before the queue went side by side; folded into the
      // phase detail it keeps the half dense without losing "how long has this sat".
      const detail = [phase.detail, `Created ${formatDate(row.createdAt)}`].filter(Boolean).join(' · ');
      return (
        <Stack spacing={0.25} sx={{ py: 0.5 }}>
          <Box>
            <Chip label={phase.label} color={phase.color} size="small" />
          </Box>
          <Typography variant="caption" color="text.secondary" sx={tabularSx}>
            {detail}
          </Typography>
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

// --- Queue column component ---

interface PullRequestColumnProps {
  source: string;
  heading: string;
}

function PullRequestColumn({ source, heading }: PullRequestColumnProps) {
  // The id, not the row (#343). The modal stages openings and cancels the pull, both of which
  // refetch this list; holding the object would pin the modal's staging chip to the pre-staging
  // snapshot - the same trap #340 fixed in the assembly views.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  // Only the two live statuses stay on this board: completed and cancelled pulls leave the active
  // queue the moment they land, and live on under the history page instead.
  const { data, loading, error } = useQuery<{ pullRequests: PullRequest[] }>(GET_PULL_REQUESTS, {
    variables: { source, statuses: ['PENDING', 'IN_PROGRESS'] },
  });

  const requests = useMemo(() => data?.pullRequests ?? [], [data]);
  const selected = useMemo(() => requests.find((pr) => pr.id === selectedId) ?? null, [requests, selectedId]);

  const handleRowClick = (params: GridRowParams<PullRequest>) => {
    setSelectedId(params.row.id);
  };

  // minWidth:0 lets the grid column shrink instead of forcing the page sideways; the DataGrid
  // scrolls its own body when the half gets narrower than the columns.
  return (
    <Box sx={{ minWidth: 0 }}>
      <Typography variant="h6" sx={{ mb: 1 }}>
        {heading}
      </Typography>
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
    </Box>
  );
}

// --- Main component ---

export default function PullRequestQueue() {
  return (
    <Box>
      <Stack
        direction="row"
        spacing={2}
        alignItems="flex-start"
        justifyContent="space-between"
        sx={{ mb: 1.5 }}
      >
        <Box sx={{ minWidth: 0 }}>
          <Typography variant="h5" sx={{ mb: 0.5 }}>
            Pull Request Queue
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Every request to take hardware out of inventory. Open a row to start its pick, stage the
            carts and complete it.
          </Typography>
        </Box>
        {/* Completed and cancelled pulls drop off the active board; history is where they still
            live. */}
        <Button
          component={RouterLink}
          to="/app/warehouse/pull-requests/history"
          size="small"
          startIcon={<History size={16} strokeWidth={1.75} />}
          sx={{ flexShrink: 0 }}
        >
          Pull request history
        </Button>
      </Stack>

      {/* Both queues, side by side above lg and stacked below it. minWidth:0 rides on each column so
          the pair fills the row without ever widening the page. */}
      <Box
        sx={{
          display: 'grid',
          gridTemplateColumns: { xs: '1fr', lg: '1fr 1fr' },
          gap: 2,
        }}
      >
        <PullRequestColumn source="SHOP_ASSEMBLY" heading="Shop Assembly" />
        <PullRequestColumn source="SHIPPING_OUT" heading="Shipping Out" />
      </Box>
    </Box>
  );
}
