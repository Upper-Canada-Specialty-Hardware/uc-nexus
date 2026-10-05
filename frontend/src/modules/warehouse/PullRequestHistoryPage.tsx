import { useEffect, useMemo, useState } from 'react';
import { userMessage } from '../../graphql/userMessage';
import { Alert, Box, Button, Chip, Stack, ToggleButton, ToggleButtonGroup, Tooltip, Typography } from '@mui/material';
import { ChevronRight } from 'lucide-react';
import { useQuery } from '@apollo/client/react';
import type { GridColDef, GridRowParams } from '@mui/x-data-grid';
import { GET_PULL_REQUESTS } from '../../graphql/warehouse';
import DataTable from '../../components/DataTable';
import PageHeader from '../../components/PageHeader';
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

// One server page of finished pulls, newest finished first (#1268). Terminal pulls only accumulate, so
// the page reads a page at a time; a full page means older ones exist and Load more is offered.
const PAGE_SIZE = 200;

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
    resizable: false,
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

  // Both toggles are sent to the server (#1268), so a filter reaches past the first page instead of
  // narrowing only what was already loaded.
  const { data, loading, error, fetchMore } = useQuery<{ pullRequests: PullRequest[] }>(GET_PULL_REQUESTS, {
    variables: {
      statuses: statusFilter === 'ALL' ? TERMINAL_STATUSES : [statusFilter],
      source: sourceFilter === 'ALL' ? undefined : sourceFilter,
      limit: PAGE_SIZE,
      offset: 0,
      newestFinishedFirst: true,
    },
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => data?.pullRequests ?? [], [data]);

  // A changed toggle starts a fresh first page, so the end-of-list flag resets with it.
  const [reachedEnd, setReachedEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset paging when the toggles change
    setReachedEnd(false);
  }, [sourceFilter, statusFilter]);
  const hasMore = !reachedEnd && rows.length > 0 && rows.length % PAGE_SIZE === 0;

  const handleLoadMore = async () => {
    setLoadingMore(true);
    try {
      const res = await fetchMore({
        variables: { offset: rows.length },
        updateQuery: (prev, { fetchMoreResult }) => ({
          pullRequests: [...(prev.pullRequests ?? []), ...(fetchMoreResult?.pullRequests ?? [])],
        }),
      });
      if ((res.data?.pullRequests?.length ?? 0) < PAGE_SIZE) setReachedEnd(true);
    } finally {
      setLoadingMore(false);
    }
  };

  const selected = useMemo(
    () => (data?.pullRequests ?? []).find((pr) => pr.id === selectedId) ?? null,
    [data, selectedId],
  );

  const handleRowClick = (params: GridRowParams<PullRequest>) => {
    setSelectedId(params.row.id);
  };

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Pull Request History"
        parent={{ label: 'Pull Request Queue', to: '/app/warehouse/pull-requests' }}
        description="Every pull that has finished - completed or cancelled - from both the shop-assembly and shipping-out queues. Open a row to see its items and stamps."
      />

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
          Error loading pull request history: {userMessage(error, { reading: true })}
        </Alert>
      )}

      <DataTable
        columns={columns}
        storageKey="warehouse.pull-request-history"
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

      {hasMore && (
        <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'center', gap: 2, flexWrap: 'wrap' }}>
          <Typography variant="body2" color="text.secondary" sx={tabularSx}>
            Showing the newest {rows.length} - older finished pulls exist.
          </Typography>
          <Button size="small" variant="outlined" onClick={handleLoadMore} disabled={loadingMore}>
            {loadingMore ? 'Loading…' : 'Load more'}
          </Button>
        </Box>
      )}

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
