import { useState, useMemo, useCallback } from 'react';
import { Alert, Box, Typography } from '@mui/material';
import { DataGrid, type GridColDef } from '@mui/x-data-grid';
import { useQuery, useMutation } from '@apollo/client/react';
import { GET_GP_OUTBOX, GET_GP_OUTBOX_SUMMARY } from '../graphql/shared';
import { RETRY_GP_OUTBOX_ENTRY, CANCEL_GP_OUTBOX_ENTRY } from '../graphql/admin';
import ConfirmDialog from './ConfirmDialog';
import { useGridColumnFit } from './useGridColumnFit';
import { buildGpWriteQueueColumns, type OutboxEntry } from './gpWriteQueueColumns';
import { useToast } from './Toast';
import { microLabelSx, monoSx, tabularSx } from '../theme';
import { useIdentity } from '../hooks/useIdentity';

interface GpWriteQueuePanelProps {
  /**
   * The relay operations to list, e.g. `['create_po']`. Left out, the panel lists every write, which
   * is what the admin queue wants. Pass a module-level constant: a fresh array on every render is
   * compared by value by Apollo, but a stable one keeps the query identity obvious.
   */
  ops?: string[];
  /**
   * #854: only writes in these states. The PO table passes the ones that still need someone -
   * waiting, in flight, failed - so succeeded history never piles up above its rows. Left out, every
   * state is listed, which is what the admin queue wants. Pass a module-level constant, like `ops`.
   */
  statuses?: string[];
  heading?: string;
  /**
   * The mounting inside a module (#754): the columns that only an admin reads are dropped, and the
   * panel renders nothing at all while there is no held write, so the page it sits on is unchanged
   * in the normal case.
   */
  compact?: boolean;
}

// An `ambiguous` write reached the relay and we do not know what GP did with it. Retrying it can
// genuinely create a duplicate receipt or a second PO number, so the confirm text has to say so -
// the backend cannot know, and must not pretend to.
const AMBIGUOUS_RETRY_WARNING =
  'This write may already have posted in GP. Retrying could create a duplicate. Check GP first.';
const NORMAL_RETRY_WARNING =
  'This puts the write back on the queue with a fresh attempt budget. It will be sent as soon as the GP relay is connected.';

// #1216: who may retry or cancel a held write, by the GP-side op it is waiting to make - the same map
// as `_ROLES_BY_RELAY_OP` in backend/app/schemas/gp_outbox.py, which refuses everyone else. Anything
// not listed is a tenant owner's. Mirrored here so a person never confirms an action only to be told
// it is not theirs.
const ROLES_BY_RELAY_OP: Record<string, string[]> = {
  create_po: ['PO Manager', 'PO User'],
  create_receipt: ['Warehouse Manager'],
};

const ROLE_LABEL_BY_RELAY_OP: Record<string, string> = {
  create_po: 'a PO Manager or PO User',
  create_receipt: 'a Warehouse Manager',
};

function gpWriteGateReason(relayOp: string): string {
  return `Only ${ROLE_LABEL_BY_RELAY_OP[relayOp] ?? 'a Tenant Owner'} can retry or cancel this write.`;
}

export default function GpWriteQueuePanel({ ops, statuses, heading, compact }: GpWriteQueuePanelProps) {
  const { showToast } = useToast();
  const { ownsTenant, roles } = useIdentity();
  // Keyed on the role names, not the array, so the columns are not rebuilt on every render.
  const rolesKey = roles.join('|');
  // Tenant owners and UC Nexus admins hold every op (the backend's role sets all include them).
  const canActOn = useMemo(() => {
    const held = new Set(rolesKey.split('|'));
    return (relayOp: string) => ownsTenant || (ROLES_BY_RELAY_OP[relayOp] ?? []).some((role) => held.has(role));
  }, [ownsTenant, rolesKey]);
  const [retryTarget, setRetryTarget] = useState<OutboxEntry | null>(null);
  const [cancelTarget, setCancelTarget] = useState<OutboxEntry | null>(null);

  const variables = useMemo(() => ({ ...(ops ? { ops } : {}), ...(statuses ? { statuses } : {}) }), [ops, statuses]);

  const { data, loading, error } = useQuery<{ gpOutbox: OutboxEntry[] }>(GET_GP_OUTBOX, {
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

  const columns: GridColDef[] = useMemo(
    () =>
      buildGpWriteQueueColumns({
        compact,
        canActOn,
        gateReason: gpWriteGateReason,
        onRetry: setRetryTarget,
        onCancel: setCancelTarget,
      }),
    [compact, canActOn],
  );

  // #909: the columns fit the panel's width instead of scrolling sideways, and a person's resized
  // widths are remembered - apart for the admin queue and a module's compact mounting, whose column
  // sets differ.
  const { setContainer, gridProps: fit } = useGridColumnFit(compact ? 'gp-write-queue.compact' : 'gp-write-queue.admin', columns);

  const handleRetry = useCallback(() => {
    if (retryTarget) retryEntry({ variables: { id: retryTarget.id } });
  }, [retryTarget, retryEntry]);

  const handleCancel = useCallback(() => {
    if (cancelTarget) cancelEntry({ variables: { id: cancelTarget.id } });
  }, [cancelTarget, cancelEntry]);

  // A module page is not the place to announce an empty queue: with nothing held, the panel takes no
  // space at all. The admin queue keeps its table either way, because an admin came looking for it.
  // #1280: a failed poll is not an empty queue. With nothing on screen to show, say the list could not
  // be read rather than vanish, so writes stuck behind a failing read are not mistaken for none held.
  if (compact && entries.length === 0) {
    if (!error) return null;
    return (
      <Alert severity="warning" sx={{ mb: 2.5 }}>
        Could not load held GP writes: {error.message}
      </Alert>
    );
  }

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
        ref={setContainer}
        {...fit}
        rows={entries}
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
        sx={[fit.sx, { '& .ts-cell': { ...monoSx, ...tabularSx, color: 'text.secondary' } }]}
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
