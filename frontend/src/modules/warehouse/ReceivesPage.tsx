import { useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Chip,
  CircularProgress,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery } from '@apollo/client/react';
import { GET_RECEIVES } from '../../graphql/warehouse';
import { GET_PROJECTS } from '../../graphql/shared';
import BackToModule from '../../components/BackToModule';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
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

export default function ReceivesPage() {
  const [projectId, setProjectId] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [poSearch, setPoSearch] = useState('');

  const { data: projectsData } = useQuery<{ projects: Project[] }>(GET_PROJECTS);
  const { data, loading, error } = useQuery<{ receives: ReceiveRow[] }>(GET_RECEIVES, {
    variables: {
      limit: 200,
      offset: 0,
      projectId: projectId || undefined,
      poSearch: poSearch.trim() || undefined,
    },
    fetchPolicy: 'cache-and-network',
  });

  // Status is filtered client-side: the server returns one interleaved list and the counts on
  // screen should agree with what the filter narrowed, not with a second round trip.
  const rows = useMemo(() => {
    const all = data?.receives ?? [];
    return statusFilter ? all.filter((r) => r.status === statusFilter) : all;
  }, [data, statusFilter]);

  const columns = useMemo<GridColDef<ReceiveRow>[]>(
    () => [
      {
        field: 'occurredAt',
        headerName: 'Date',
        width: 130,
        valueFormatter: (value: string) => parseServerDate(value).toLocaleDateString(),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 160,
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
        renderCell: (params) => (
          <Typography component="span" sx={monoSx}>
            {(params.value as string | null) ?? '—'}
          </Typography>
        ),
      },
      { field: 'projectName', headerName: 'Project', flex: 1, minWidth: 150 },
      { field: 'lineCount', headerName: 'Lines', type: 'number', width: 90 },
      { field: 'totalQuantity', headerName: 'Qty', type: 'number', width: 90 },
      {
        field: 'receiptNumber',
        headerName: 'RCT #',
        width: 140,
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

  return (
    <Box sx={{ p: 3 }}>
      <BackToModule to="/app/warehouse" label="Warehouse" />
      <Typography variant="h5" sx={{ mb: 0.5 }}>
        Receives
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: 3 }}>
        Every delivery written down against a purchase order, whatever stage it reached - including
        the ones that were rejected.
      </Typography>

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

      {error && <Alert severity="error">{error.message}</Alert>}

      {loading && !data ? (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 6 }}>
          <CircularProgress />
        </Box>
      ) : rows.length === 0 ? (
        <Alert severity="info">No receives match these filters.</Alert>
      ) : (
        <>
          <DataGrid
            rows={rows}
            columns={columns}
            density="compact"
            disableRowSelectionOnClick
            initialState={{ pagination: { paginationModel: { pageSize: 50 } } }}
            pageSizeOptions={[25, 50, 100]}
          />
          <Box sx={{ mt: 1.5 }}>
            <Typography sx={microLabelSx}>Showing</Typography>
            <Typography sx={{ ...tabularSx, fontWeight: 700 }}>{rows.length} receive(s)</Typography>
          </Box>
        </>
      )}
    </Box>
  );
}
