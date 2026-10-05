import { useEffect, useMemo, useState } from 'react';
import { userMessage } from '../../graphql/userMessage';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useGridColumnFit } from '../../components/useGridColumnFit';
import { useQuery } from '@apollo/client/react';
import LoadError from '../../components/LoadError';
import { GET_RECEIVES } from '../../graphql/warehouse';
import { GET_PROJECTS } from '../../graphql/shared';
import PageHeader from '../../components/PageHeader';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import { useOnCompanySwitch } from '../../hooks/useDropProjectOnCompanySwitch';
import type { Project } from '../../types/project';

/**
 * Every receive entity in one place (#505).
 *
 * The existing surfaces each cover a slice - MyReceiveDraftsView is one user's own drafts,
 * ReceiveApprovalsPage is the manager's pending queue, ReceivingHistory is recent activity on the
 * receiving page. A REJECTED draft appeared in none of them, so a count somebody disputed vanished
 * from the product entirely and the only way to find it was to ask the person who raised it.
 *
 * Drafts and booked records are interleaved because they are the same thing at different stages:
 * what the warehouse wants is "every delivery we have written down", newest first.
 */

interface ReceiveRow {
  kind: 'DRAFT' | 'RECORD';
  id: string;
  occurredAt: string;
  status: string;
  poId: string;
  poNumber: string | null;
  projectId: string | null;
  projectName: string | null;
  lineCount: number;
  totalQuantity: number;
  countedBy: string | null;
  reviewedBy: string | null;
  rejectionReason: string | null;
  receiptNumber: string | null;
  batchNumber: string | null;
}

const STATUS_LABEL: Record<string, string> = {
  PENDING_APPROVAL: 'Pending approval',
  APPROVING: 'Approving',
  REJECTED: 'Rejected',
  APPROVED: 'Approved',
};

const STATUS_COLOR: Record<string, 'default' | 'warning' | 'info' | 'error' | 'success'> = {
  PENDING_APPROVAL: 'warning',
  APPROVING: 'info',
  REJECTED: 'error',
  APPROVED: 'success',
};

const STATUS_FILTERS = ['', 'PENDING_APPROVAL', 'APPROVING', 'REJECTED', 'APPROVED'];

// One server page. A full page means older receives may exist, so Load more is offered.
const PAGE_SIZE = 200;

export default function ReceivesPage() {
  const [projectId, setProjectId] = useState('');
  // #1537: the picked project belongs to the company it was picked in; kept across a switch, the list read
  // under the new company comes back empty, as if it had none.
  useOnCompanySwitch(() => setProjectId(''));
  const [statusFilter, setStatusFilter] = useState('');
  const [poSearch, setPoSearch] = useState('');

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  // Every filter, status included, is applied by the server (#1267). Status used to narrow the first
  // page in the browser, so past one page an older rejected receive read as "nothing matches".
  const { data, loading, error, fetchMore, refetch } = useQuery<{ receives: ReceiveRow[] }>(GET_RECEIVES, {
    variables: {
      limit: PAGE_SIZE,
      offset: 0,
      projectId: projectId || undefined,
      poSearch: poSearch.trim() || undefined,
      status: statusFilter || undefined,
    },
    fetchPolicy: 'cache-and-network',
  });

  const rows = useMemo(() => data?.receives ?? [], [data]);

  // A changed filter starts a fresh first page, so the end-of-list flag resets with it.
  const [reachedEnd, setReachedEnd] = useState(false);
  const [loadingMore, setLoadingMore] = useState(false);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- reset paging when the filters change
    setReachedEnd(false);
  }, [projectId, statusFilter, poSearch]);
  const hasMore = !reachedEnd && rows.length > 0 && rows.length % PAGE_SIZE === 0;

  const handleLoadMore = async () => {
    setLoadingMore(true);
    try {
      const res = await fetchMore({
        variables: { offset: rows.length },
        updateQuery: (prev, { fetchMoreResult }) => ({
          receives: [...(prev.receives ?? []), ...(fetchMoreResult?.receives ?? [])],
        }),
      });
      if ((res.data?.receives?.length ?? 0) < PAGE_SIZE) setReachedEnd(true);
    } finally {
      setLoadingMore(false);
    }
  };

  const columns = useMemo<GridColDef<ReceiveRow>[]>(
    () => [
      {
        field: 'occurredAt',
        headerName: 'Date',
        width: 130,
        minWidth: 110,
        valueFormatter: (value: string) => parseServerDate(value).toLocaleDateString(),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 160,
        minWidth: 130,
        renderCell: (params) => (
          <Chip
            size="small"
            label={STATUS_LABEL[params.value as string] ?? (params.value as string)}
            color={STATUS_COLOR[params.value as string] ?? 'default'}
          />
        ),
      },
      {
        field: 'poNumber',
        headerName: 'PO #',
        width: 150,
        minWidth: 110,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {(params.value as string | null) ?? '—'}
          </Typography>
        ),
      },
      { field: 'projectName', headerName: 'Project', flex: 1, minWidth: 150 },
      { field: 'lineCount', headerName: 'Lines', type: 'number', width: 90, minWidth: 80 },
      { field: 'totalQuantity', headerName: 'Qty', type: 'number', width: 90, minWidth: 80 },
      {
        field: 'receiptNumber',
        headerName: 'RCT #',
        width: 140,
        minWidth: 110,
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {(params.value as string | null) ?? '—'}
          </Typography>
        ),
      },
      { field: 'countedBy', headerName: 'Counted by', flex: 1, minWidth: 140 },
      { field: 'reviewedBy', headerName: 'Reviewed by', flex: 1, minWidth: 140 },
    ],
    [],
  );

  // #909: the columns fit the grid's width and never scroll sideways; resized widths are remembered.
  const { setContainer, gridProps } = useGridColumnFit('warehouse.receives', columns as GridColDef[]);

  return (
    <Box sx={{ p: 3 }}>
      <PageHeader
        title="Receives"
        parent={{ label: 'Warehouse', to: '/app/warehouse' }}
        description="Every delivery written down against a purchase order, whatever stage it reached - including the ones that were rejected."
        sx={{ mb: 3 }}
      />

      <Stack direction={{ xs: 'column', sm: 'row' }} spacing={2} sx={{ mb: 2 }}>
        <TextField
          select
          size="small"
          label="Project"
          value={projectId}
          onChange={(e) => setProjectId(e.target.value)}
          sx={{ minWidth: 220 }}
        >
          <MenuItem value="">All projects</MenuItem>
          {(projectsData?.projects ?? []).map((p) => (
            <MenuItem key={p.id} value={p.id}>
              {p.description || p.projectId}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          select
          size="small"
          label="Status"
          value={statusFilter}
          onChange={(e) => setStatusFilter(e.target.value)}
          sx={{ minWidth: 190 }}
        >
          {STATUS_FILTERS.map((s) => (
            <MenuItem key={s || 'all'} value={s}>
              {s ? (STATUS_LABEL[s] ?? s) : 'All statuses'}
            </MenuItem>
          ))}
        </TextField>
        <TextField
          size="small"
          label="PO number"
          placeholder="Search…"
          value={poSearch}
          onChange={(e) => setPoSearch(e.target.value)}
          sx={{ minWidth: 200 }}
        />
      </Stack>

      {/* #1582: a failed read is not an empty filter result - say so, with a retry. */}
      {error && !data && <LoadError what="the receives" error={error} onRetry={() => refetch()} />}
      {error && data && <Alert severity="warning">{userMessage(error, { reading: true })}</Alert>}

      {error && !data ? null : loading && !data ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      ) : rows.length === 0 ? (
        <Alert severity="info">No receives match these filters.</Alert>
      ) : (
        <>
          <DataGrid
            ref={setContainer}
            {...gridProps}
            rows={rows}
            density="compact"
            disableRowSelectionOnClick
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
            pageSizeOptions={[25, 50, 100]}
          />
          <Box sx={{ mt: 1.5, display: 'flex', alignItems: 'flex-end', gap: 2, flexWrap: 'wrap' }}>
            <Box>
              <Typography sx={microLabelSx}>Showing</Typography>
              <Typography sx={{ ...tabularSx, fontWeight: 700 }}>
                {rows.length} receive(s){hasMore ? ', newest first - older ones exist' : ''}
              </Typography>
            </Box>
            {hasMore && (
              <Button size="small" variant="outlined" onClick={handleLoadMore} disabled={loadingMore}>
                {loadingMore ? 'Loading…' : 'Load more'}
              </Button>
            )}
          </Box>
        </>
      )}
    </Box>
  );
}
