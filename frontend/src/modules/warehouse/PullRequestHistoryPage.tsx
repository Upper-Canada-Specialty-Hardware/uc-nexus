import { useMemo, useState } from 'react';
import { Alert, Box, Chip, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import { ChevronRight } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PULL_REQUESTS } from '../../graphql/warehouse';
import DataTable from '../../components/DataTable';
import BackToModule from '../../components/BackToModule';
import PullRequestDetailModal from './PullRequestDetailModal';
import type { PullRequest } from './PullRequestQueue';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';

// The finished counterpart of the live queue: one table of every pull that reached a terminal state,
// from both sources. The queue drops a pull the moment it completes or is cancelled, so without this
// there is nowhere to answer "when did this go out / why was it cancelled" after the fact.

// Both terminal states in one fetch, from every project (pull requests carry no project selector -
// the same all-projects read the queue does). Held at module scope so the reference is stable and
// the query is not re-issued on every render.
const TERMINAL_STATUSES = ['COMPLETED', 'CANCELLED'];

type SourceFilter = 'ALL' | 'SHOP_ASSEMBLY' | 'SHIPPING_OUT';
type StatusFilter = 'ALL' | 'COMPLETED' | 'CANCELLED';

// --- Status config (shared shape with the queue and the modal) ---

const STATUS_CHIP_COLOR: Record<string, 'warning' | 'info' | 'success' | 'error' | 'default'> = {
  PENDING: 'warning',
  IN_PROGRESS: 'info',
  COMPLETED: 'success',
  CANCELLED: 'error',
};

const SOURCE_CHIP_COLOR: Record<string, 'primary' | 'secondary' | 'default'> = {
  SHOP_ASSEMBLY: 'primary',
  SHIPPING_OUT: 'secondary',
};

function formatStatus(status: string): string {
  return status
    .split('_')
    .map((w) => w.charAt(0) + w.slice(1).toLowerCase())
    .join(' ');
}

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return parseServerDate(dateStr).toLocaleString();
}

// --- Columns ---

const columns: GridColDef[] = [
  {
    field: 'requestNumber',
    headerName: 'Request #',
    flex: 1,
    minWidth: 150,
    renderCell: (params) => (
      <Typography component="span" sx={{ ...monoSx, fontWeight: 600 }}>
        {params.value as string}
      </Typography>
    ),
  },
  {
    field: 'source',
    headerName: 'Source',
    flex: 1,
    minWidth: 150,
    renderCell: (params) => (
      <Chip
        label={formatStatus(params.value as string)}
        color={SOURCE_CHIP_COLOR[params.value as string] ?? 'default'}
        size="small"
      />
    ),
  },
  {
    field: 'status',
    headerName: 'Status',
    flex: 0.8,
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
    // The moment the pull left the queue, and who was on it. The two terminal states record it in
    // different columns: cancelledAt/cancelledBy for a cancellation, completedAt for a completion.
    // There is no completedBy in the schema, so the picker (pickedBy) stands in as the actor.
    field: 'when',
    headerName: 'When + Who',
    flex: 1.2,
    minWidth: 200,
    valueGetter: (_value: unknown, row: PullRequest) => {
      const iso = row.status === 'CANCELLED' ? row.cancelledAt : row.completedAt;
      return iso ? parseServerDate(iso).getTime() : 0;
    },
    renderCell: (params) => {
      const row = params.row as PullRequest;
      const cancelled = row.status === 'CANCELLED';
      const iso = cancelled ? row.cancelledAt : row.completedAt;
      const who = cancelled ? row.cancelledBy : row.pickedBy;
      const cell = (
        <Stack spacing={0.25} sx={{ py: 0.5 }}>
          <Typography variant="body2" sx={tabularSx}>
            {formatDateTime(iso)}
          </Typography>
          {who && (
            <Typography variant="caption" color="text.secondary">
              by {who}
            </Typography>
          )}
        </Stack>
      );
      // The reason is the whole point of a cancelled row, but it is prose - hovering keeps it off the
      // grid rather than widening the column to hold a sentence.
      return cancelled && row.cancellationReason ? (
        <Tooltip title={row.cancellationReason}>
          <Box>{cell}</Box>
        </Tooltip>
      ) : (
        cell
      );
    },
  },
  {
    field: 'itemsCount',
    headerName: 'Items',
    flex: 0.6,
    minWidth: 90,
    type: 'number',
    valueGetter: (_value: unknown, row: PullRequest) => row.items?.length ?? 0,
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

// --- Component ---

export default function PullRequestHistoryPage() {
  const [sourceFilter, setSourceFilter] = useState<SourceFilter>('ALL');
  const [statusFilter, setStatusFilter] = useState<StatusFilter>('ALL');
  // The id, not the row (mirrors the queue): the modal refetches this list, and holding the object
  // would pin its view to the pre-refetch snapshot.
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const { data, loading, error } = useQuery<{ pullRequests: PullRequest[] }>(GET_PULL_REQUESTS, {
    variables: { statuses: TERMINAL_STATUSES },
    fetchPolicy: 'cache-and-network',
  });

  // Both filters are applied client-side over the single fetched list, so the on-screen count agrees
  // with what the toggles narrowed rather than a second round trip.
  const rows = useMemo(() => {
    let list = data?.pullRequests ?? [];
    if (sourceFilter !== 'ALL') list = list.filter((pr) => pr.source === sourceFilter);
    if (statusFilter !== 'ALL') list = list.filter((pr) => pr.status === statusFilter);
    return list;
  }, [data, sourceFilter, statusFilter]);

  const selected = useMemo(
    () => (data?.pullRequests ?? []).find((pr) => pr.id === selectedId) ?? null,
    [data, selectedId],
  );

  const handleRowClick = (params: GridRowParams<PullRequest>) => {
    setSelectedId(params.row.id);
  };

  return (
    <Box sx={{ p: 3 }}>
      <BackToModule to="/app/warehouse/pull-requests" label="Pull Request Queue" />
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Pull Request History
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Every pull that has finished - completed or cancelled - from both the shop-assembly and
        shipping-out queues. Open a row to see its items and stamps.
      </Typography>

      <Stack direction="row" spacing={3} sx={{ mb: 2 }} flexWrap="wrap" useFlexGap>
        <Box sx={{ minWidth: 0 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
            Source
          </Typography>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={sourceFilter}
            onChange={(_event, value: SourceFilter | null) => {
              if (value) setSourceFilter(value);
            }}
          >
            <ToggleButton value="ALL">All</ToggleButton>
            <ToggleButton value="SHOP_ASSEMBLY">Shop Assembly</ToggleButton>
            <ToggleButton value="SHIPPING_OUT">Shipping Out</ToggleButton>
          </ToggleButtonGroup>
        </Box>
        <Box sx={{ minWidth: 0 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
            Status
          </Typography>
          <ToggleButtonGroup
            size="small"
            exclusive
            value={statusFilter}
            onChange={(_event, value: StatusFilter | null) => {
              if (value) setStatusFilter(value);
            }}
          >
            <ToggleButton value="ALL">All</ToggleButton>
            <ToggleButton value="COMPLETED">Completed</ToggleButton>
            <ToggleButton value="CANCELLED">Cancelled</ToggleButton>
          </ToggleButtonGroup>
        </Box>
      </Stack>

      {/* Without this, a failed load reads as an empty history - the one thing this screen must never
          claim wrongly. */}
      {error && (
        <Alert severity="error" sx={{ mb: 1.5 }}>
          Error loading pull request history: {error.message}
        </Alert>
      )}

      <DataTable
        columns={columns}
        rows={rows}
        loading={loading}
        onRowClick={handleRowClick}
        // The When + Who cell is a date over a line of detail; the default 52px row clips it.
        rowHeight={64}
        height={560}
        initialState={{
          sorting: { sortModel: [{ field: 'when', sort: 'desc' }] },
          pagination: { paginationModel: { pageSize: 25 } },
        }}
        pageSizeOptions={[25, 50, 100]}
        localeText={{ noRowsLabel: 'No finished pull requests' }}
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
