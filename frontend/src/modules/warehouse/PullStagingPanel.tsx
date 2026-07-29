import { useCallback, useMemo, useState } from 'react';
import { Alert, Box, Button, Checkbox, Chip, Stack, Typography } from '@mui/material';
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
import { leafIdentity } from '../../utils/leaf';
import { microLabelSx, monoSx, tabularSx } from '../../theme';
import { FadeIn } from '../../motion';
import { parseServerDate } from '../../utils/serverDate';

function openingLabel(opening: PullStagingOpening): string {
  return leafIdentity(opening.openingNumber, opening.leaf);
}

function formatDateTime(value: string | null): string {
  if (!value) return '';
  return parseServerDate(value).toLocaleString();
}

/** "1 leaf" / "3 leaves". A raw "leaf(s)" is a machine string, not something you say to a person. */
function leafCount(n: number): string {
  return `${n} ${n === 1 ? 'leaf' : 'leaves'}`;
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
 * The warehouse's per-leaf staging checklist (#343, laid out as sections in #367).
 *
 * A pull is picked cart by cart, so the unit of confirmation here is one door leaf and its hardware
 * lines - not the whole pull. Each leaf confirmed flips to Staged on its own and becomes assignable
 * on the assembly floor immediately; the pull completes when the last one is ticked, and the panel
 * says so rather than leaving the user to infer it from a disappearing button.
 *
 * The flat table this used to be is now a section per leaf, matching the pick screen. A cart is a
 * leaf's worth of hardware, and a table row with a bulleted list crammed into one cell was a section
 * pretending to be a row - it read worst at exactly the moment it mattered, standing at the bench
 * with six lines to check off.
 *
 * Confirming is deliberately a two-step (tick, then Confirm) rather than a checkbox that fires on
 * click: staging is a statement that hardware is physically on a cart, and a mis-click should not
 * make that claim.
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
          ? `All carts staged - ${pullRequestNumber} is complete.`
          : 'Carts staged. Those leaves are now available for assembly.',
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
          Stage carts ({stagedCount} of {openings.length} leaves)
        </Typography>
        {editable && stageable.length > 0 && (
          <Button size="small" variant="text" onClick={toggleAll}>
            {selected.size === stageable.length ? 'Clear selection' : 'Select all remaining'}
          </Button>
        )}
      </Stack>

      {editable && stageable.length > 0 && (
        <Alert severity="info" sx={{ mb: 2 }}>
          Confirm a leaf once its cart is built. Each one becomes available for assembly straight
          away - you do not have to finish the whole pull first.
        </Alert>
      )}

      {openings.map((opening) => {
        const stageableRow = isStageable(opening);
        const where = [opening.building, opening.floor].filter(Boolean).join(' / ');
        return (
          <Box
            key={opening.id}
            component="section"
            data-testid={`staging-row-${opening.id}`}
            sx={{
              mb: 2,
              border: '1px solid',
              borderColor: 'divider',
              borderRadius: '6px',
              // The amber edge marks what is selected; a staged cart carries the success hue
              // instead, because that is real state rather than a selection.
              borderLeft: '3px solid',
              borderLeftColor: selected.has(opening.id)
                ? 'secondary.main'
                : stageableRow
                  ? 'divider'
                  : 'success.main',
              p: 1.5,
            }}
          >
            <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1 }}>
              {editable && (
                <Checkbox
                  size="small"
                  sx={{ p: 0.5 }}
                  checked={selected.has(opening.id)}
                  disabled={!stageableRow}
                  onChange={() => toggle(opening.id)}
                  inputProps={{ 'aria-label': `Stage ${openingLabel(opening)}` }}
                />
              )}
              <Box sx={{ flexGrow: 1, minWidth: 0 }}>
                <Typography component="div" sx={{ ...monoSx, fontWeight: 600 }}>
                  {openingLabel(opening)}
                </Typography>
                {where && (
                  <Typography component="div" variant="caption" color="text.secondary">
                    {where}
                  </Typography>
                )}
              </Box>
              {stageableRow ? (
                <Chip label="Not staged" size="small" />
              ) : (
                /* The confirmed section's tag rises in: the checkbox flow is unchanged, but the
                   claim "this cart is built" gets a beat of its own when it lands. */
                <FadeIn y={4}>
                  <Stack spacing={0.25} alignItems="flex-end">
                    <Chip label="Staged" color="success" size="small" />
                    {opening.stagedBy && (
                      <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                        {opening.stagedBy} {formatDateTime(opening.stagedAt)}
                      </Typography>
                    )}
                  </Stack>
                </FadeIn>
              )}
              {opening.assemblyStatus === 'COMPLETED' ? (
                <Chip label="Assembled" color="success" size="small" variant="outlined" />
              ) : opening.assemblyStatus === 'IN_PROGRESS' ? (
                <Chip label="In Progress" color="info" size="small" variant="outlined" />
              ) : (
                <Typography variant="caption" color="text.secondary">
                  {opening.assignedTo ?? 'Unassigned'}
                </Typography>
              )}
            </Stack>

            {opening.items.length === 0 ? (
              <Typography variant="body2" color="text.secondary">
                No lines
              </Typography>
            ) : (
              <Box component="table" sx={{ width: '100%', borderCollapse: 'collapse' }}>
                <Box component="tbody">
                  {opening.items.map((item) => (
                    <Box
                      component="tr"
                      key={item.id}
                      sx={{ '& td': { borderTop: '1px solid', borderColor: 'divider', py: 0.5 } }}
                    >
                      <Box component="td" sx={{ width: '35%' }}>
                        <Typography variant="body2" color="text.secondary">
                          {item.hardwareCategory}
                        </Typography>
                      </Box>
                      <Box component="td" sx={monoSx}>
                        {item.productCode}
                      </Box>
                      <Box component="td" sx={{ ...tabularSx, textAlign: 'right', width: 60 }}>
                        {/* The pick count is the ALLOCATED quantity - that is what the pull line
                            asks for and what was reserved. Owed is shown only when it differs, so
                            the puller can see the cart is deliberately short rather than wondering
                            whether they miscounted. */}
                        {item.allocatedQuantity}
                        {item.quantity > item.allocatedQuantity && (
                          <Typography component="div" variant="caption" color="text.secondary">
                            of {item.quantity} owed
                          </Typography>
                        )}
                      </Box>
                    </Box>
                  ))}
                </Box>
              </Box>
            )}
          </Box>
        );
      })}

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
            ? `Confirm the last ${leafCount(selected.size)} of ${pullRequestNumber} as staged? This completes the pull.`
            : `Confirm ${leafCount(selected.size)} of ${pullRequestNumber} as staged? They become available for assembly immediately.`
        }
        confirmLabel="Confirm staged"
        cancelLabel="Cancel"
        onConfirm={handleConfirm}
        onCancel={() => setConfirmOpen(false)}
      />
    </Box>
  );
}
