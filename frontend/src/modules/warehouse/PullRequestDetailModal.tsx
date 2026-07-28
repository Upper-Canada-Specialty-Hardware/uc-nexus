import { useState, useCallback } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Box,
  Typography,
  Chip,
  Button,
  Alert,
  Stack,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  TextField,
  Divider,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import {
  CANCEL_PULL_REQUEST,
  COMPLETE_PULL_REQUEST,
  START_PULL_REQUEST_PICK,
} from '../../graphql/warehouse';
import {
  PULL_CANCEL_REFETCH_QUERIES,
  PULL_CANCEL_STALE_ROOT_FIELDS,
  PULL_LIFECYCLE_STALE_ROOT_FIELDS,
} from '../../graphql/refetch';
import { useIdentity } from '../../hooks/useIdentity';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import PullStagingPanel from './PullStagingPanel';
import { isCancellable, pullPhase } from './pullStaging';
import type { PullRequest } from './PullRequestQueue';
import { leafIdentity } from '../../utils/leaf';
import { microLabelSx, monoSx, tabularSx } from '../../theme';

// --- Status config ---

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

function formatDate(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleDateString();
}

function formatDateTime(dateStr: string | null | undefined): string {
  if (!dateStr) return '-';
  return new Date(dateStr).toLocaleString();
}

// --- Props ---

interface PullRequestDetailModalProps {
  open: boolean;
  pr: PullRequest;
  onClose: () => void;
  onRefetch: () => void;
}

// --- Helper component ---

/** One field of the pull's identity card. Two columns, one line each — no 200px label gutter. */
function InfoRow({
  label,
  value,
  mono,
  tabular,
}: {
  label: string;
  value: string;
  mono?: boolean;
  tabular?: boolean;
}) {
  return (
    <Box>
      <Typography component="div" sx={microLabelSx}>
        {label}
      </Typography>
      <Typography
        component="div"
        variant="body2"
        sx={{ ...(mono ? monoSx : {}), ...(tabular ? tabularSx : {}) }}
      >
        {value}
      </Typography>
    </Box>
  );
}

/** A ruled break between the modal's sections, with the section's own micro-label. */
function SectionHeading({ children, sx }: { children: React.ReactNode; sx?: object }) {
  return (
    <Typography
      component="div"
      sx={{
        ...microLabelSx,
        pb: 0.75,
        mb: 1.5,
        borderBottom: '2px solid',
        borderColor: 'text.primary',
        ...sx,
      }}
    >
      {children}
    </Typography>
  );
}

// --- Component ---

export default function PullRequestDetailModal({
  open,
  pr,
  onClose,
  onRefetch,
}: PullRequestDetailModalProps) {
  const { displayName } = useIdentity();
  const { showToast } = useToast();
  const navigate = useNavigate();

  // Confirm dialog state
  const [confirmCompleteOpen, setConfirmCompleteOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  // #343: a cancel refused because assembly has already started. The server names every blocker in
  // one message, so it is shown verbatim and the dialog stays open - the user is being told what to
  // go and finish, not just that it failed.
  const [cancelBlockedMessage, setCancelBlockedMessage] = useState<string | null>(null);
  const closeCancelDialog = useCallback(() => {
    setCancelOpen(false);
    setCancelBlockedMessage(null);
  }, []);

  const looseItems = pr.items.filter((item) => item.itemType === 'LOOSE');
  const openingItems = pr.items.filter((item) => item.itemType === 'OPENING_ITEM');

  // The availability lookup that used to live here is gone with the approve gate (#367). It answered
  // "will approving this succeed", and approving no longer moves anything - real per-location
  // availability is on the pick page, where the person who can see the rack is looking at it.

  // --- Mutations ---

  // Eviction only, disjoint from the queue refetch the parent does in onRefetch (see refetch.ts).
  // #343 re-keyed workability from "the pull is COMPLETED" to "this opening is PULLED", so approving
  // and completing both change what the assembly floor can see - and the assembly floor is a
  // different module, never mounted while a warehouse user is working the pull.
  const evictPullLifecycleFields = (cache: { evict: (o: { id: string; fieldName: string }) => void; gc: () => void }) => {
    for (const fieldName of PULL_LIFECYCLE_STALE_ROOT_FIELDS) {
      cache.evict({ id: 'ROOT_QUERY', fieldName });
    }
    cache.gc();
  };

  const [startPick, { loading: startLoading }] = useMutation(START_PULL_REQUEST_PICK, {
    update: evictPullLifecycleFields,
    onCompleted: () => {
      // Straight to the pick page (#367): starting a pick is not a decision with an outcome to
      // report, it is the first step of the picking job, and stopping to show a toast over a modal
      // the user is about to leave would be ceremony.
      navigate(`/app/warehouse/pull-requests/${pr.id}/pick`);
    },
    onError: (error) => showToast(error.message, 'error'),
  });

  const [completePR, { loading: completeLoading }] = useMutation(COMPLETE_PULL_REQUEST, {
    update: evictPullLifecycleFields,
    onCompleted: () => {
      setConfirmCompleteOpen(false);
      showToast('Pull Request completed successfully', 'success');
      onRefetch();
    },
    onError: (error) => {
      setConfirmCompleteOpen(false);
      showToast(error.message, 'error');
    },
  });

  const [cancelPR, { loading: cancelLoading }] = useMutation(CANCEL_PULL_REQUEST, {
    refetchQueries: PULL_CANCEL_REFETCH_QUERIES,
    update(cache) {
      // Disjoint from the refetch list (see refetch.ts).
      for (const field of PULL_CANCEL_STALE_ROOT_FIELDS) {
        cache.evict({ id: 'ROOT_QUERY', fieldName: field });
      }
      cache.gc();
    },
    onCompleted: (data) => {
      const result = (
        data as {
          cancelPullRequest?: {
            restocked?: { quantity: number }[];
            reservationsRecreated?: boolean;
            integrityNote?: string | null;
          };
        }
      )?.cancelPullRequest;
      const units = (result?.restocked ?? []).reduce((sum, r) => sum + r.quantity, 0);
      setCancelOpen(false);
      setCancelBlockedMessage(null);
      if (result?.integrityNote) {
        // The hardware came back but could not be re-claimed for the request. That is a real state
        // the acceptor has to know about, so it is a warning, not a success.
        showToast(result.integrityNote, 'warning');
      } else {
        showToast(
          `Pull cancelled. ${units} unit(s) returned to inventory` +
            (result?.reservationsRecreated ? ' and reserved for the request again.' : '.'),
          'success',
        );
      }
      onRefetch();
    },
    onError: (error) => {
      setCancelBlockedMessage(error.message);
    },
  });

  // --- Handlers ---

  const handleComplete = () => {
    completePR({ variables: { id: pr.id, completedBy: displayName } });
  };

  const handleCancel = () => {
    setCancelBlockedMessage(null);
    cancelPR({
      variables: {
        input: { id: pr.id, cancelledBy: displayName, reason: cancelReason.trim() || null },
      },
    });
  };

  // --- Visibility rules ---

  const isPending = pr.status === 'PENDING';
  const isInProgress = pr.status === 'IN_PROGRESS';
  const isCompleted = pr.status === 'COMPLETED';
  const isCancelled = pr.status === 'CANCELLED';

  const isPicked = Boolean(pr.pickedAt);
  const isAssignedToCurrentUser = isInProgress && pr.assignedTo === displayName;
  const isLockedToOtherUser = isInProgress && pr.assignedTo !== displayName;

  // #343: the staging checklist is the shop-assembly pull's execution view. Since #367 it appears
  // only once the pick is confirmed - staging is a claim that a cart is built, and before the pick
  // the hardware is still on the shelf. It stays visible after completion, read-only, so the record
  // of who staged what survives the pull being finished.
  const showStaging = pr.source === 'SHOP_ASSEMBLY' && ((isInProgress && isPicked) || isCompleted);
  const canCancel = isCancellable(pr);
  const phase = pullPhase(pr);

  // --- Action buttons ---

  // Destructive action sits hard left, away from the confirming action on the right.
  const cancelButton = canCancel ? (
    <Button
      variant="outlined"
      color="error"
      onClick={() => setCancelOpen(true)}
      disabled={cancelLoading}
      sx={{ mr: 'auto' }}
    >
      Cancel Pull
    </Button>
  ) : null;

  const goToPick = () => navigate(`/app/warehouse/pull-requests/${pr.id}/pick`);

  let actionButtons: React.ReactNode | undefined;

  if (isPending) {
    // No availability gate any more (#367): starting a pick moves nothing, and whether the stock is
    // there is a question the pick screen answers per location rather than one this button guesses
    // at from an aggregate.
    actionButtons = (
      <Button
        variant="contained"
        color="secondary"
        onClick={() => startPick({ variables: { id: pr.id, startedBy: displayName } })}
        disabled={startLoading}
      >
        {startLoading ? 'Starting...' : 'Start pick'}
      </Button>
    );
  } else if (isInProgress && !isPicked && !isLockedToOtherUser) {
    // Locked-out users fall through to the cancel-only branch below. Two people keying the same
    // paper sheet against one pull would each be entering rows the other cannot see, and
    // `confirm_pick` does not check the assignment - the button is the only thing standing there.
    actionButtons = (
      <>
        {cancelButton}
        <Button variant="contained" color="secondary" onClick={goToPick}>
          Resume pick
        </Button>
      </>
    );
  } else if (isAssignedToCurrentUser) {
    actionButtons = (
      <>
        {cancelButton}
        <Button
          variant="contained"
          color="secondary"
          onClick={() => setConfirmCompleteOpen(true)}
          disabled={completeLoading}
        >
          {completeLoading ? 'Completing...' : 'Mark as Pulled'}
        </Button>
      </>
    );
  } else if (canCancel) {
    actionButtons = cancelButton;
  }

  // --- Render ---

  return (
    <>
      <Modal
        open={open}
        title={`PR: ${pr.requestNumber}`}
        onClose={onClose}
        actions={actionButtons}
        maxWidth="md"
        // Nothing here is unsaved (the cancel reason lives in its own dialog), so Escape simply
        // dismisses the pull. The nested Confirm/Cancel dialogs are siblings, not children, so
        // their own Escape never reaches this handler.
        onKeyDown={(event) => {
          if (event.key === 'Escape') {
            event.stopPropagation();
            onClose();
          }
        }}
      >
        {/* Header: Status + Info */}
        <Box sx={{ mb: 2 }}>
          <Stack direction="row" spacing={1} alignItems="center" sx={{ mb: 1.5 }} flexWrap="wrap" useFlexGap>
            <Chip
              label={formatStatus(pr.source)}
              color={SOURCE_CHIP_COLOR[pr.source] ?? 'default'}
              size="small"
            />
            <Chip
              label={formatStatus(pr.status)}
              color={STATUS_CHIP_COLOR[pr.status] ?? 'default'}
              size="small"
            />
            <Chip label={phase.label} color={phase.color} size="small" variant="outlined" />
            {phase.detail && (
              <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                {phase.detail}
              </Typography>
            )}
          </Stack>
          <Box
            sx={{
              display: 'grid',
              gridTemplateColumns: { xs: '1fr', sm: '1fr 1fr' },
              columnGap: 3,
              rowGap: 1.25,
            }}
          >
            <InfoRow label="Request #" value={pr.requestNumber} mono />
            <InfoRow label="Created Date" value={formatDate(pr.createdAt)} tabular />
            <InfoRow label="Requested By" value={pr.requestedBy} />
            <InfoRow label="Assigned To" value={pr.assignedTo ?? '-'} />
          </Box>
        </Box>

        {/* Completed info */}
        {isCompleted && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="success.main" sx={tabularSx}>
              Completed at: {formatDateTime(pr.completedAt)}
            </Typography>
          </Box>
        )}

        {/* Cancelled info */}
        {isCancelled && (
          <Box sx={{ mb: 2 }}>
            <Alert severity="error">
              This Pull Request was cancelled at {formatDateTime(pr.cancelledAt)}
              {pr.cancelledBy ? ` by ${pr.cancelledBy}` : ''}
              {pr.cancellationReason ? `: ${pr.cancellationReason}` : '.'}
              {' '}Its hardware was returned to inventory and the source request went back to Pending.
            </Alert>
          </Box>
        )}

        {/* Started / picked stamps (#367). Two moments now, and the difference matters: started is
            "the warehouse opened this", picked is "the stock has left the shelf". */}
        {(isInProgress || isCompleted) && pr.approvedAt && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary" sx={tabularSx}>
              Pick started: {formatDateTime(pr.approvedAt)}
            </Typography>
            {isPicked && (
              <Typography variant="body2" color="text.secondary" sx={tabularSx}>
                Pick confirmed: {formatDateTime(pr.pickedAt)}
                {pr.pickedBy ? ` by ${pr.pickedBy}` : ''}
              </Typography>
            )}
          </Box>
        )}

        {isInProgress && !isPicked && (
          <Alert severity={pr.partiallyPicked ? 'error' : 'info'} sx={{ mb: 2 }}>
            {pr.partiallyPicked
              ? 'This pick was confirmed short. Some hardware is off the shelf and the rest is outstanding - open the pick sheet to enter the remainder.'
              : 'Nothing has left inventory yet. Open the pick sheet to record what comes off each location.'}
          </Alert>
        )}

        {/* Locked to other user banner */}
        {isLockedToOtherUser && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Locked to {pr.assignedTo}
          </Alert>
        )}

        <Divider sx={{ mb: 2 }} />

        {/* Per-opening staging checklist (#343). Read-only once the pull is complete. */}
        {showStaging && (
          <PullStagingPanel
            pullRequestId={pr.id}
            pullRequestNumber={pr.requestNumber}
            editable={isInProgress}
            onStaged={(completed) => {
              if (completed) onRefetch();
            }}
          />
        )}

        {/* Items table */}
        <SectionHeading>Items ({pr.items.length})</SectionHeading>

        {pr.items.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No items in this pull request.
          </Typography>
        ) : (
          <>
            {/* Loose Items */}
            {looseItems.length > 0 && (
              <Box sx={{ mb: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Loose Items ({looseItems.length})
                </Typography>
                {/* The Available Qty and Status columns are gone with the approve gate (#367).
                    They forecast whether approval would succeed, off a project-wide aggregate; the
                    pick page shows the real numbers per location to the person at the rack. */}
                <Table size="small" sx={{ '& td': { fontSize: '0.8125rem' } }}>
                  <TableHead>
                    <TableRow>
                      <TableCell>Product Code</TableCell>
                      <TableCell>Hardware Category</TableCell>
                      <TableCell>Leaf</TableCell>
                      <TableCell align="right">Requested Qty</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {looseItems.map((item) => (
                      <TableRow key={item.id} hover>
                        <TableCell sx={monoSx}>{item.productCode ?? '-'}</TableCell>
                        <TableCell>{item.hardwareCategory ?? '-'}</TableCell>
                        <TableCell sx={monoSx}>{leafIdentity(item.openingNumber, item.leaf)}</TableCell>
                        <TableCell align="right">{item.requestedQuantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}

            {/* Opening Items */}
            {openingItems.length > 0 && (
              <Box sx={{ mb: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Assembled Opening Items ({openingItems.length})
                </Typography>
                <Table size="small" sx={{ '& td': { fontSize: '0.8125rem' } }}>
                  <TableHead>
                    <TableRow>
                      {/* #335: a pair ships as two lines. Without the leaf they read identically. */}
                      <TableCell>Leaf</TableCell>
                      <TableCell align="right">Requested Qty</TableCell>
                      <TableCell>Collected</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {openingItems.map((item) => (
                      <TableRow key={item.id} hover>
                        <TableCell sx={monoSx}>{leafIdentity(item.openingNumber, item.leaf)}</TableCell>
                        <TableCell align="right">{item.requestedQuantity}</TableCell>
                        <TableCell>
                          {item.fetchedAt ? (
                            <Typography variant="caption" color="text.secondary" sx={tabularSx}>
                              {item.fetchedBy} {formatDateTime(item.fetchedAt)}
                            </Typography>
                          ) : (
                            <Typography variant="body2" color="text.secondary">
                              Not yet
                            </Typography>
                          )}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
          </>
        )}
      </Modal>

      {/* Confirm: Complete */}
      <ConfirmDialog
        open={confirmCompleteOpen}
        title="Complete Pull Request"
        message={
          showStaging
            ? `Mark Pull Request ${pr.requestNumber} as pulled? Any opening not yet confirmed will be staged as well.`
            : `Mark Pull Request ${pr.requestNumber} as pulled? This action cannot be undone.`
        }
        confirmLabel="Mark as Pulled"
        cancelLabel="Cancel"
        onConfirm={handleComplete}
        onCancel={() => setConfirmCompleteOpen(false)}
      />

      {/* Cancel: its own dialog rather than ConfirmDialog, because it takes a reason and has to be
          able to show the server's blocker list without closing. Closing clears that blocker list:
          it names openings as they were at the moment of the refusal, and re-opening the dialog
          after somebody has gone and finished them would otherwise re-assert a stale accusation. */}
      <Modal
        open={cancelOpen}
        title={`Cancel ${pr.requestNumber}`}
        onClose={closeCancelDialog}
        maxWidth="sm"
        actions={
          <Stack direction="row" spacing={1}>
            <Button onClick={closeCancelDialog}>Keep pull</Button>
            <Button variant="contained" color="error" onClick={handleCancel} disabled={cancelLoading}>
              {cancelLoading ? 'Cancelling...' : 'Cancel pull and restock'}
            </Button>
          </Stack>
        }
      >
        <Alert severity="warning" sx={{ mb: 2 }}>
          Every unit this pull took will go back into project inventory, its openings return to the
          not-pulled state, and the request that raised it goes back to Pending for re-acceptance.
          Openings whose assembly has already started will block the cancellation.
        </Alert>
        {cancelBlockedMessage && (
          <Alert severity="error" sx={{ mb: 2 }} data-testid="cancel-blocked">
            {cancelBlockedMessage}
          </Alert>
        )}
        <TextField
          label="Reason (optional)"
          value={cancelReason}
          onChange={(e) => setCancelReason(e.target.value)}
          fullWidth
          multiline
          minRows={2}
          slotProps={{ htmlInput: { maxLength: 500 } }}
        />
      </Modal>
    </>
  );
}
