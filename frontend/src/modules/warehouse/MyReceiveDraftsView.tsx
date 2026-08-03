import { useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { useApolloClient } from '@apollo/client/react';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import { GET_RECEIVE_DRAFTS, DELETE_RECEIVE_DRAFT } from '../../graphql/warehouse';
import { RECEIVE_DRAFT_REFETCH_QUERIES } from '../../graphql/refetch';
import { microLabelSx, monoSx } from '../../theme';
import { parseServerDate } from '../../utils/serverDate';
import ReceiveDraftEditModal from './ReceiveDraftEditModal';
import type { ReceiveDraft } from './receiveDraftTypes';

const DASH = '—';

function formatDateTime(value: string | null): string {
  if (!value) return DASH;
  const d = parseServerDate(value);
  return isNaN(d.getTime()) ? DASH : d.toLocaleString();
}

function DraftCard({
  draft,
  onEdit,
  onDelete,
}: {
  draft: ReceiveDraft;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const rejected = draft.status === 'REJECTED';
  return (
    <Paper variant="outlined" sx={{ p: 2 }}>
      <Box sx={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 2, mb: 1 }}>
        <Typography sx={{ ...monoSx, fontWeight: 700 }}>{draft.poNumber ?? 'Unknown PO'}</Typography>
        <Chip
          size="small"
          color={rejected ? 'error' : 'warning'}
          label={rejected ? 'Sent back' : 'Awaiting approval'}
        />
      </Box>
      <Typography variant="body2" color="text.secondary">
        {draft.totalQuantity} {draft.totalQuantity === 1 ? 'unit' : 'units'} · submitted{' '}
        {formatDateTime(draft.createdAt)}
      </Typography>
      {rejected && draft.rejectionReason && (
        <Alert severity="error" sx={{ mt: 1.5 }}>
          <Typography variant="body2">
            {draft.reviewedBy ?? 'A reviewer'} sent this back: {draft.rejectionReason}
          </Typography>
        </Alert>
      )}
      <Stack direction="row" spacing={1} sx={{ mt: 1.5 }}>
        <Button size="small" variant={rejected ? 'contained' : 'outlined'} onClick={onEdit}>
          {rejected ? 'Edit & Resubmit' : 'Edit'}
        </Button>
        <Button size="small" color="error" onClick={onDelete}>
          Delete
        </Button>
      </Stack>
    </Paper>
  );
}

/**
 * What a warehouse user's own counts are doing.
 *
 * The queue a manager works from is somebody else's screen; this is the other half - the person who
 * unloaded the truck needs to know their count is still waiting, or that it came back and why.
 * Rejected drafts sit at the top because they are the only ones with anything to do.
 */
export default function MyReceiveDraftsView() {
  const { showToast } = useToast();
  const client = useApolloClient();
  const [editing, setEditing] = useState<ReceiveDraft | null>(null);
  const [deleting, setDeleting] = useState<ReceiveDraft | null>(null);

  const { data, loading, error } = useQuery<{ receiveDrafts: ReceiveDraft[] }>(GET_RECEIVE_DRAFTS, {
    variables: { mine: true },
    fetchPolicy: 'cache-and-network',
  });
  const [deleteDraft] = useMutation(DELETE_RECEIVE_DRAFT);

  const drafts = data?.receiveDrafts ?? [];
  const rejected = drafts.filter((d) => d.status === 'REJECTED');
  const pending = drafts.filter((d) => d.status === 'PENDING_APPROVAL');

  const handleDelete = async () => {
    if (!deleting) return;
    try {
      await deleteDraft({ variables: { id: deleting.id } });
      showToast('Draft deleted.', 'success');
      await client.refetchQueries({ include: RECEIVE_DRAFT_REFETCH_QUERIES });
    } catch (err: unknown) {
      showToast(err instanceof Error ? err.message : 'Deleting this draft failed', 'error');
    } finally {
      setDeleting(null);
    }
  };

  return (
    <Box>
      {loading && drafts.length === 0 && (
        <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
          <CircularProgress />
        </Box>
      )}
      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          Error loading your drafts: {error.message}
        </Alert>
      )}
      {!loading && !error && drafts.length === 0 && (
        <Alert severity="info">
          You have no receives waiting on approval. Counted deliveries appear here until a Warehouse
          Manager posts them.
        </Alert>
      )}

      {rejected.length > 0 && (
        <Box sx={{ mb: 3 }}>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1, color: 'error.main' }}>
            Sent back — needs your attention
          </Typography>
          <Stack spacing={1.5}>
            {rejected.map((draft) => (
              <DraftCard
                key={draft.id}
                draft={draft}
                onEdit={() => setEditing(draft)}
                onDelete={() => setDeleting(draft)}
              />
            ))}
          </Stack>
        </Box>
      )}

      {pending.length > 0 && (
        <Box>
          <Typography component="div" sx={{ ...microLabelSx, mb: 1 }}>
            Awaiting approval
          </Typography>
          <Stack spacing={1.5}>
            {pending.map((draft) => (
              <DraftCard
                key={draft.id}
                draft={draft}
                onEdit={() => setEditing(draft)}
                onDelete={() => setDeleting(draft)}
              />
            ))}
          </Stack>
        </Box>
      )}

      <ReceiveDraftEditModal open={editing !== null} draft={editing} onClose={() => setEditing(null)} />

      <ConfirmDialog
        open={deleting !== null}
        title="Delete this draft?"
        message={`The count of ${deleting?.totalQuantity ?? 0} units against ${deleting?.poNumber ?? 'this PO'} is lost. Nothing has been posted to GP, so you can re-enter it from Receiving.`}
        confirmLabel="Delete"
        onConfirm={handleDelete}
        onCancel={() => setDeleting(null)}
      />
    </Box>
  );
}
