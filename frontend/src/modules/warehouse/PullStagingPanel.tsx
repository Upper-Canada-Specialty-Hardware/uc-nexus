import { useCallback, useMemo, useState } from 'react';
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableRow,
  Typography,
} from '@mui/material';
import { useMutation, useQuery } from '@apollo/client/react';
import { GET_PULL_REQUEST_OPENINGS, STAGE_PULL_OPENINGS } from '../../graphql/warehouse';
import {
  PULL_STAGING_REFETCH_QUERIES,
  PULL_STAGING_STALE_ROOT_FIELDS,
} from '../../graphql/refetch';
import { useToast } from '../../components/Toast';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useIdentity } from '../../hooks/useIdentity';
import { isStageable, type PullStagingOpening } from './pullStaging';
import { leafLabel } from '../../utils/leaf';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';

function openingLabel(opening: PullStagingOpening): string {
  const leaf = leafLabel(opening.leaf);
  return `${opening.openingNumber ?? 'Opening'}${leaf ? ` - ${leaf}` : ''}`;
}

function formatDateTime(value: string | null): string {
  if (!value) return '';
  return new Date(value).toLocaleString();
}

// --- Component ---------------------------------------------------------------------------------

interface PullStagingPanelProps {
  pullRequestId: string;
  pullRequestNumber: string;
  /** Staging only applies to an approved pull. The panel renders read-only otherwise. */
  editable: boolean;
  onStaged?: (completed: boolean) => void;
}

/**
 * The warehouse's per-opening staging checklist (#343).
 *
 * A pull is picked cart by cart, so the unit of confirmation here is one opening and its hardware
 * lines - not the whole pull. Each opening confirmed flips to Staged on its own and becomes
 * assignable on the assembly floor immediately; the pull completes when the last one is ticked, and
 * the panel says so rather than leaving the user to infer it from a disappearing button.
 *
 * Confirming is deliberately a two-step (tick, then Confirm) rather than a checkbox that fires on
 * click: staging is a statement that hardware is physically on a cart, and a mis-click on a
 * virtualized list should not make that claim.
 */
export default function PullStagingPanel({
  pullRequestId,
  pullRequestNumber,
  editable,
  onStaged,
}: PullStagingPanelProps) {
  const { showToast } = useToast();
  const { displayName } = useIdentity();
  const [selected, setSelected] = useState<Set<string>>(new Set());
  const [confirmOpen, setConfirmOpen] = useState(false);

  const { data, loading, refetch } = useQuery<{ pullRequestOpenings: PullStagingOpening[] }>(
    GET_PULL_REQUEST_OPENINGS,
    { variables: { pullRequestId } },
  );

  const openings = useMemo(() => data?.pullRequestOpenings ?? [], [data]);
  const stageable = useMemo(() => openings.filter(isStageable), [openings]);
  const stagedCount = openings.length - stageable.length;

  const [stageOpenings, { loading: staging }] = useMutation(STAGE_PULL_OPENINGS, {
    refetchQueries: PULL_STAGING_REFETCH_QUERIES,
    update(cache) {
      // Disjoint from the refetch list above (see refetch.ts): evicting a field a mounted query
      // also refetches makes Apollo run the heavy resolver twice concurrently.
      for (const field of PULL_STAGING_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName: field });
      }
      cache.gc();
    },
    onCompleted: (result) => {
      const payload = (result as { stagePullOpenings?: { completed?: boolean } })?.stagePullOpenings;
      setSelected(new Set());
      setConfirmOpen(false);
      showToast(
        payload?.completed
          ? `All openings staged - ${pullRequestNumber} is complete.`
          : 'Openings staged. They are now available for assembly.',
        'success',
      );
      refetch();
      onStaged?.(Boolean(payload?.completed));
    },
    onError: (error) => {
      setConfirmOpen(false);
      showToast(error.message, 'error');
    },
  });

  const toggle = useCallback((id: string) => {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }, []);

  const toggleAll = useCallback(() => {
    setSelected((prev) => (prev.size === stageable.length ? new Set() : new Set(stageable.map((o) => o.id))));
  }, [stageable]);

  const handleConfirm = () => {
    stageOpenings({
      variables: {
        input: {
          pullRequestId,
          openingIds: Array.from(selected),
          stagedBy: displayName,
        },
      },
    });
  };

  if (loading && !data) {
    return (
      <Typography variant="body2" color="text.secondary">
        Loading openings...
      </Typography>
    );
  }

  if (openings.length === 0) {
    return null;
  }

  const stagingAll = selected.size > 0 && selected.size === stageable.length;

  return (
    <Box sx={{ mb: 2 }}>
      <Stack
        direction="row"
        spacing={1}
        alignItems="center"
        sx={{ mb: 1.5, pb: 0.75, borderBottom: '2px solid', borderColor: 'text.primary' }}
      >
        <Typography component="div" sx={{ ...microLabelSx, flexGrow: 1 }}>
          Staging ({stagedCount} of {openings.length} openings)
        </Typography>
        {editable && stageable.length > 0 && (
          <Button size="small" variant="text" onClick={toggleAll}>
            {selected.size === stageable.length ? 'Clear selection' : 'Select all remaining'}
          </Button>
        )}
      </Stack>

      {editable && stageable.length > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Confirm an opening once its cart is built. Each one becomes available for assembly
          straight away - you do not have to finish the whole pull first.
        </Alert>
      )}

      <Table size="small">
        <TableHead>
          <TableRow>
            {editable && <TableCell padding="checkbox" />}
            <TableCell>Opening</TableCell>
            <TableCell>Location</TableCell>
            <TableCell>Hardware</TableCell>
            <TableCell>Staging</TableCell>
            <TableCell>Assembly</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {openings.map((opening) => {
            const stageableRow = isStageable(opening);
            return (
              <TableRow key={opening.id} hover data-testid={`staging-row-${opening.id}`}>
                {editable && (
                  <TableCell padding="checkbox">
                    <Checkbox
                      checked={selected.has(opening.id)}
                      disabled={!stageableRow}
                      onChange={() => toggle(opening.id)}
                      inputProps={{ 'aria-label': `Stage ${openingLabel(opening)}` }}
                    />
                  </TableCell>
                )}
                <TableCell sx={monoSx}>{openingLabel(opening)}</TableCell>
                <TableCell>
                  {[opening.building, opening.floor].filter(Boolean).join(' / ') || '-'}
                </TableCell>
                <TableCell>
                  {opening.items.length === 0 ? (
                    <Typography variant="body2" color="text.secondary">
                      No lines
                    </Typography>
                  ) : (
                    <Box component="ul" sx={{ m: 0, pl: 2 }}>
                      {opening.items.map((item) => (
                        <Box component="li" key={item.id} sx={monoSx}>
                          {/* The pick count is the ALLOCATED quantity - that is what the pull line
                              asks for and what was reserved. Owed is shown only when it differs, so
                              the puller can see the cart is deliberately short rather than wondering
                              whether they miscounted. */}
                          {item.allocatedQuantity} x {item.productCode} ({item.hardwareCategory})
                          {item.quantity > item.allocatedQuantity && (
                            <Typography component="span" variant="caption" color="text.secondary">
                              {' '}
                              - {item.quantity - item.allocatedQuantity} of {item.quantity} owed
                              never pulled
                            </Typography>
                          )}
                        </Box>
                      ))}
                    </Box>
                  )}
                </TableCell>
                <TableCell>
                  {stageableRow ? (
                    <Chip label="Not staged" size="small" />
                  ) : (
                    /* The confirmed row's tag rises in: the checkbox flow is unchanged, but the
                       claim "this cart is built" gets a beat of its own when it lands. */
                    <FadeIn y={4}>
                      <Stack spacing={0.5} alignItems="flex-start">
                        <Chip label="Staged" color="success" size="small" />
                        {opening.stagedBy && (
                          <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                            {opening.stagedBy} {formatDateTime(opening.stagedAt)}
                          </Typography>
                        )}
                      </Stack>
                    </FadeIn>
                  )}
                </TableCell>
                <TableCell>
                  {opening.assemblyStatus === 'COMPLETED' ? (
                    <Chip label="Assembled" color="success" size="small" />
                  ) : opening.assemblyStatus === 'IN_PROGRESS' ? (
                    <Chip label="In Progress" color="info" size="small" />
                  ) : (
                    <Typography variant="body2" color="text.secondary">
                      {opening.assignedTo ?? 'Unassigned'}
                    </Typography>
                  )}
                </TableCell>
              </TableRow>
            );
          })}
        </TableBody>
      </Table>

      {editable && (
        <Stack direction="row" spacing={1} sx={{ mt: 2 }}>
          <Button
            variant="contained"
            // Ink, not amber: the dialog's footer action is this surface's single amber accent.
            color="primary"
            disabled={selected.size === 0 || staging}
            onClick={() => setConfirmOpen(true)}
          >
            {staging ? 'Confirming...' : `Confirm ${selected.size} staged`}
          </Button>
        </Stack>
      )}

      <ConfirmDialog
        open={confirmOpen}
        title="Confirm staged openings"
        message={
          stagingAll
            ? `Confirm the last ${selected.size} opening(s) of ${pullRequestNumber} as staged? This completes the pull.`
            : `Confirm ${selected.size} opening(s) of ${pullRequestNumber} as staged? They become available for assembly immediately.`
        }
        confirmLabel="Confirm staged"
        cancelLabel="Cancel"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
}
