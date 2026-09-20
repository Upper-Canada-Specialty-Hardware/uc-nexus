import { useState, useMemo, useCallback } from 'react';
import { Box, Button, Chip, Stack, Typography } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_GP_OUTBOX, GET_GP_OUTBOX_SUMMARY } from '../graphql/shared';
import { RETRY_GP_OUTBOX_ENTRY, CANCEL_GP_OUTBOX_ENTRY } from '../graphql/admin';
import ConfirmDialog from './ConfirmDialog';
import { useToast } from './Toast';
import { microLabelSx, monoSx, tabularSx } from '../theme';
import { parseServerDate } from '../utils/serverDate';

interface OutboxEntry {
  id: string;
  label: string;
  op: string;
  company: string;
  status: string;
  attempts: number;
  nextAttemptAt: string;
  lastError: string | null;
  failureKind: string | null;
  entityKey: string;
  createdAt: string;
}

interface GpWriteQueuePanelProps {
  /**
   * The relay operations to list, e.g. `['create_po']`. Left out, the panel lists every write, which
   * is what the admin queue wants. Pass a module-level constant: a fresh array on every render is
   * compared by value by Apollo, but a stable one keeps the query identity obvious.
   */
  ops?: string[];
  heading?: string;
  /**
   * The mounting inside a module (#754): the columns that only an admin reads are dropped, and the
   * panel renders nothing at all while there is no held write, so the page it sits on is unchanged
   * in the normal case.
   */
  compact?: boolean;
}

function fmtDate(v: string | null | undefined): string {
  return v ? parseServerDate(v).toLocaleString() : '—';
}

const STATUS_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error'> = {
  PENDING: 'warning',
  IN_FLIGHT: 'warning',
  SUCCEEDED: 'success',
  FAILED: 'error',
  CANCELLED: 'default',
};

// An `ambiguous` write reached the relay and we do not know what GP did with it. Retrying it can
// genuinely create a duplicate receipt or a second PO number, so the confirm text has to say so -
// the backend cannot know, and must not pretend to.
const AMBIGUOUS_RETRY_WARNING =
  'This write may already have posted in GP. Retrying could create a duplicate. Check GP first.';
const NORMAL_RETRY_WARNING =
  'This puts the write back on the queue with a fresh attempt budget. It will be sent as soon as the GP relay is connected.';

// The columns the compact mounting keeps. The company is the caller's own one, and the queued-at
// time is an admin's forensic detail, so neither earns its width inside a module.
const COMPACT_FIELDS = ['label', 'status', 'attempts', 'nextAttemptAt', 'lastError', 'actions'];

export default function GpWriteQueuePanel({ ops, heading, compact }: GpWriteQueuePanelProps) {
  const { showToast } = useToast();
  const [retryTarget, setRetryTarget] = useState<OutboxEntry | null>(null);
  const [cancelTarget, setCancelTarget] = useState<OutboxEntry | null>(null);

  const variables = useMemo(() => (ops ? { ops } : {}), [ops]);

  const { data, loading } = useQuery<{ gpOutbox: OutboxEntry[] }>(GET_GP_OUTBOX, {
    variables,
    fetchPolicy: 'cache-and-network',
    // Long enough not to be chatty, short enough that a drain shows up while an admin is watching.
    pollInterval: 15_000,
  });
  const entries = useMemo(() => data?.gpOutbox ?? [], [data]);

  // The list is refetched with this panel's own variables: a filtered mounting and the admin queue
  // are separate cache entries, and only the one on screen needs re-reading after an action.
  const refetchAfterAction = useMemo(
    () => [{ query: GET_GP_OUTBOX, variables }, { query: GET_GP_OUTBOX_SUMMARY }],
    [variables],
  );

  const [retryEntry, { loading: retrying }] = useMutation(RETRY_GP_OUTBOX_ENTRY, {
    refetchQueries: refetchAfterAction,
    onCompleted: () => {
      setRetryTarget(null);
      showToast('Queued for retry', 'success');
    },
    onError: (err) => {
      setRetryTarget(null);
      showToast(err.message, 'error');
    },
  });

  const [cancelEntry, { loading: cancelling }] = useMutation(CANCEL_GP_OUTBOX_ENTRY, {
    refetchQueries: refetchAfterAction,
    onCompleted: () => {
      setCancelTarget(null);
      showToast('Queue entry cancelled', 'success');
    },
    onError: (err) => {
      setCancelTarget(null);
      showToast(err.message, 'error');
    },
  });

  const columns: GridColDef[] = useMemo(() => {
    const all: GridColDef[] = [
      { field: 'label', headerName: 'Write', flex: 1, minWidth: 220 },
      {
        field: 'company',
        headerName: 'Company',
        width: 100,
        renderCell: (p) => (
          <Box component="span" sx={monoSx}>
            {p.row.company}
          </Box>
        ),
      },
      {
        field: 'status',
        headerName: 'Status',
        width: 120,
        renderCell: (p) => (
          <Chip size="small" label={p.row.status} color={STATUS_COLOR[p.row.status] ?? 'default'} />
        ),
      },
      { field: 'attempts', headerName: 'Tries', width: 80, type: 'number', headerAlign: 'right', align: 'right' },
      {
        field: 'failureKind',
        headerName: 'Failure',
        width: 130,
        valueFormatter: (v: string | null) => v ?? '—',
      },
      { field: 'lastError', headerName: 'Last error', flex: 1, minWidth: 220, valueFormatter: (v: string | null) => v ?? '—' },
      {
        field: 'nextAttemptAt',
        headerName: 'Next attempt',
        flex: 1,
        minWidth: 170,
        valueFormatter: (v: string) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'createdAt',
        headerName: 'Queued at',
        flex: 1,
        minWidth: 170,
        valueFormatter: (v: string) => fmtDate(v),
        cellClassName: 'ts-cell',
      },
      {
        field: 'actions',
        headerName: 'Actions',
        width: 170,
        sortable: false,
        filterable: false,
        renderCell: (p) => {
          const row = p.row as OutboxEntry;
          const canRetry = row.status === 'FAILED' || row.status === 'CANCELLED';
          const canCancel = row.status === 'PENDING' || row.status === 'FAILED';
          return (
            <Stack direction="row" spacing={1}>
              <Button size="small" disabled={!canRetry} onClick={() => setRetryTarget(row)}>
                Retry
              </Button>
              <Button size="small" color="error" disabled={!canCancel} onClick={() => setCancelTarget(row)}>
                Cancel
              </Button>
            </Stack>
          );
        },
      },
    ];
    return compact ? all.filter((c) => COMPACT_FIELDS.includes(c.field)) : all;
  }, [compact]);

  const handleRetry = useCallback(() => {
    if (retryTarget) retryEntry({ variables: { id: retryTarget.id } });
  }, [retryTarget, retryEntry]);

  const handleCancel = useCallback(() => {
    if (cancelTarget) cancelEntry({ variables: { id: cancelTarget.id } });
  }, [cancelTarget, cancelEntry]);

  // A module page is not the place to announce an empty queue: with nothing held, the panel takes no
  // space at all. The admin queue keeps its table either way, because an admin came looking for it.
  if (compact && entries.length === 0) return null;

  return (
    <Box sx={{ mt: compact ? 0 : 4, mb: compact ? 2.5 : 0, minWidth: 0 }}>
      <Typography component="div" sx={{ ...microLabelSx, mb: 0.5 }}>
        {heading ?? 'GP write queue'}
      </Typography>
      <Typography variant="body2" color="text.secondary" sx={{ mb: compact ? 1 : 2 }}>
        {compact
          ? 'These post themselves when the GP relay reconnects; only a failed entry needs a person.'
          : 'Receives and PO registrations that were accepted while the GP relay was unreachable. These post themselves when it reconnects; only a failed entry needs a person.'}
      </Typography>

      <DataGrid
        rows={entries}
        columns={columns}
        loading={loading}
        autoHeight
        // A handful of rows in the normal case, and the row actions must always be reachable - see
        // the same note on the installs grid.
        disableVirtualization
        disableRowSelectionOnClick
        // Inside a module every row is already on the one page, so the paginator would be a band of
        // chrome under a two-row grid.
        hideFooter={compact && entries.length <= 10}
        pageSizeOptions={[10, 25, 50]}
        initialState={{ pagination: { paginationModel: { pageSize: 10 } } }}
        sx={{ '& .ts-cell': { ...monoSx, ...tabularSx, color: 'text.secondary' } }}
      />

      <ConfirmDialog
        open={retryTarget !== null}
        title={`Retry "${retryTarget?.label ?? ''}"?`}
        message={retryTarget?.failureKind === 'ambiguous' ? AMBIGUOUS_RETRY_WARNING : NORMAL_RETRY_WARNING}
        confirmLabel={retrying ? 'Queueing…' : 'Retry'}
        onConfirm={handleRetry}
        onCancel={() => setRetryTarget(null)}
      />

      <ConfirmDialog
        open={cancelTarget !== null}
        title={`Cancel "${cancelTarget?.label ?? ''}"?`}
        message="This abandons the write. It will never reach GP, and whoever submitted it will have to redo it."
        confirmLabel={cancelling ? 'Cancelling…' : 'Cancel the write'}
        confirmColor="error"
        onConfirm={handleCancel}
        onCancel={() => setCancelTarget(null)}
      />
    </Box>
  );
}
