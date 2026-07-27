import { useState, useMemo } from 'react';
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
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import { useMutation, useQuery } from '@apollo/client/react';
import {
  APPROVE_PULL_REQUEST,
  CANCEL_PULL_REQUEST,
  COMPLETE_PULL_REQUEST,
  GET_INVENTORY_HIERARCHY,
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
import { isCancellable, stagingChipColor, stagingChipLabel } from './pullStaging';
import type { PullRequest, PullRequestItem } from './PullRequestQueue';
import { leafLabel } from '../../utils/leaf';

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

// --- Inventory lookup types ---

interface InventoryProductCode {
  productCode: string;
  totalQuantity: number;
  // Issue #229: net of deficient units (quantity - deficient_quantity) - the approve gate's basis.
  totalAvailableQuantity: number;
}

interface InventoryCategoryGroup {
  hardwareCategory: string;
  totalQuantity: number;
  totalAvailableQuantity: number;
  productCodes: InventoryProductCode[];
}

// #224: per-combo shortfall returned by approvePullRequest when the pull is blocked.
interface InventoryShortfall {
  hardwareCategory: string;
  productCode: string;
  requested: number;
  available: number;
  short: number;
}

// --- Props ---

interface PullRequestDetailModalProps {
  open: boolean;
  pr: PullRequest;
  onClose: () => void;
  onRefetch: () => void;
}

// --- Helper component ---

function InfoRow({ label, value }: { label: string; value: string }) {
  return (
    <Box sx={{ display: 'flex', py: 0.5 }}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 200, flexShrink: 0 }}>
        {label}:
      </Typography>
      <Typography variant="body2">{value}</Typography>
    </Box>
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

  // Confirm dialog state
  const [confirmApproveOpen, setConfirmApproveOpen] = useState(false);
  const [confirmCompleteOpen, setConfirmCompleteOpen] = useState(false);
  const [cancelOpen, setCancelOpen] = useState(false);
  const [cancelReason, setCancelReason] = useState('');
  // #343: a cancel refused because assembly has already started. The server names every blocker in
  // one message, so it is shown verbatim and the dialog stays open - the user is being told what to
  // go and finish, not just that it failed.
  const [cancelBlockedMessage, setCancelBlockedMessage] = useState<string | null>(null);

  // #224 gate 2: the shortfall the server returned when an approve was blocked for insufficient
  // inventory. The PR is left PENDING; we show this inline instead of cancelling.
  const [approveShortfalls, setApproveShortfalls] = useState<InventoryShortfall[]>([]);

  // Fetch inventory hierarchy for availability checks
  const { data: inventoryData } = useQuery<{ inventoryHierarchy: InventoryCategoryGroup[] }>(
    GET_INVENTORY_HIERARCHY,
    {
      variables: { projectId: pr.projectId },
      skip: pr.status !== 'PENDING',
    },
  );

  const inventoryHierarchy = inventoryData?.inventoryHierarchy ?? [];

  // Build lookup map: "category|productCode" -> available quantity. Issue #229: use the NET
  // available (quantity - deficient_quantity), the same basis as the backend approve gate, so the
  // Available Qty column and the pre-approve warning agree with what approval will actually allow.
  const availabilityMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const cat of inventoryHierarchy) {
      for (const pc of cat.productCodes) {
        const key = `${cat.hardwareCategory}|${pc.productCode}`;
        map.set(key, pc.totalAvailableQuantity);
      }
    }
    return map;
  }, [inventoryHierarchy]);

  // Get available quantity for a loose item
  function getAvailableQty(item: PullRequestItem): number {
    if (!item.hardwareCategory || !item.productCode) return 0;
    const key = `${item.hardwareCategory}|${item.productCode}`;
    return availabilityMap.get(key) ?? 0;
  }

  // Check if all loose items have sufficient inventory
  const looseItems = pr.items.filter((item) => item.itemType === 'LOOSE');
  const openingItems = pr.items.filter((item) => item.itemType === 'OPENING_ITEM');

  const allLooseSufficient = useMemo(() => {
    if (pr.status !== 'PENDING') return true;
    return looseItems.every((item) => getAvailableQty(item) >= item.requestedQuantity);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [looseItems, availabilityMap, pr.status]);

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

  const [approvePR, { loading: approveLoading }] = useMutation(APPROVE_PULL_REQUEST, {
    update: evictPullLifecycleFields,
    onCompleted: (data) => {
      const approveResult = (
        data as { approvePullRequest?: { outcome?: string; shortfalls?: InventoryShortfall[] } }
      )?.approvePullRequest;
      setConfirmApproveOpen(false);
      if (approveResult?.outcome === 'INSUFFICIENT') {
        // #224 gate 2: the pull is blocked, not cancelled. The PR stays PENDING; show the exact
        // shortfall inline and let the user know purchasing was notified to backfill. Do NOT call
        // onRefetch() here - the parent nulls selectedPR and unmounts this modal, which would drop
        // the shortfall Alert we just set. The PR row is unchanged (still PENDING), so no refetch is
        // needed to keep the list accurate.
        setApproveShortfalls(approveResult.shortfalls ?? []);
        showToast('Insufficient inventory - PR left pending; purchasing notified to backfill.', 'warning');
      } else {
        showToast('Pull Request approved. Inventory deducted.', 'success');
        onRefetch();
      }
    },
    onError: (error) => {
      setConfirmApproveOpen(false);
      showToast(error.message, 'error');
    },
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

  const handleApprove = () => {
    setApproveShortfalls([]); // clear any prior shortfall before re-attempting
    approvePR({ variables: { id: pr.id, approvedBy: displayName } });
  };

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

  const isAssignedToCurrentUser = isInProgress && pr.assignedTo === displayName;
  const isLockedToOtherUser = isInProgress && pr.assignedTo !== displayName;

  // #343: the staging checklist is the shop-assembly pull's execution view. It is shown from
  // approval onwards - including after completion, read-only, so the record of who staged what
  // survives the pull being finished.
  const showStaging = pr.source === 'SHOP_ASSEMBLY' && (isInProgress || isCompleted);
  const canCancel = isCancellable(pr);
  const stagingLabel = stagingChipLabel(pr);

  // --- Action buttons ---

  const cancelButton = canCancel ? (
    <Button variant="outlined" color="error" onClick={() => setCancelOpen(true)} disabled={cancelLoading}>
      Cancel Pull
    </Button>
  ) : null;

  let actionButtons: React.ReactNode | undefined;

  if (isPending) {
    actionButtons = (
      <Stack direction="row" spacing={1}>
        <Button
          variant="contained"
          color="primary"
          onClick={() => setConfirmApproveOpen(true)}
          disabled={approveLoading || !allLooseSufficient}
        >
          {approveLoading ? 'Approving...' : 'Approve and Start'}
        </Button>
      </Stack>
    );
  } else if (isAssignedToCurrentUser) {
    actionButtons = (
      <Stack direction="row" spacing={1}>
        {cancelButton}
        <Button
          variant="contained"
          color="primary"
          onClick={() => setConfirmCompleteOpen(true)}
          disabled={completeLoading}
        >
          {completeLoading ? 'Completing...' : 'Mark as Pulled'}
        </Button>
      </Stack>
    );
  } else if (canCancel) {
    actionButtons = <Stack direction="row" spacing={1}>{cancelButton}</Stack>;
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
      >
        {/* Header: Status + Info */}
        <Box sx={{ mb: 2 }}>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
            <Chip
              label={formatStatus(pr.source)}
              color={SOURCE_CHIP_COLOR[pr.source] ?? 'default'}
              size="medium"
            />
            <Chip
              label={formatStatus(pr.status)}
              color={STATUS_CHIP_COLOR[pr.status] ?? 'default'}
              size="medium"
            />
            {stagingLabel && (
              <Chip label={stagingLabel} color={stagingChipColor(pr)} size="medium" variant="outlined" />
            )}
          </Stack>
          <InfoRow label="Request #" value={pr.requestNumber} />
          <InfoRow label="Created Date" value={formatDate(pr.createdAt)} />
          <InfoRow label="Requested By" value={pr.requestedBy} />
          <InfoRow label="Assigned To" value={pr.assignedTo ?? '-'} />
        </Box>

        {/* Completed info */}
        {isCompleted && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="success.main">
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

        {/* Approved info */}
        {(isInProgress || isCompleted) && pr.approvedAt && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="text.secondary">
              Approved at: {formatDateTime(pr.approvedAt)}
            </Typography>
          </Box>
        )}

        {/* Insufficient inventory pre-check banner for pending PRs (#224: approving while short
            leaves the PR pending and notifies purchasing - it is no longer auto-cancelled). */}
        {isPending && !allLooseSufficient && looseItems.length > 0 && approveShortfalls.length === 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Insufficient inventory - approving will leave this PR pending and notify purchasing to backfill.
          </Alert>
        )}

        {/* Shortfall returned by a blocked approve (#224). The PR stays pending. */}
        {approveShortfalls.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            <Typography variant="body2" fontWeight="bold" gutterBottom>
              Approve blocked - insufficient inventory. PR left pending; purchasing notified to backfill.
            </Typography>
            <Box component="ul" sx={{ m: 0, pl: 2 }}>
              {approveShortfalls.map((s) => (
                <li key={`${s.hardwareCategory}|${s.productCode}`}>
                  {s.hardwareCategory} {s.productCode}: need {s.requested}, {s.available} available (short {s.short})
                </li>
              ))}
            </Box>
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
          <>
            <PullStagingPanel
              pullRequestId={pr.id}
              pullRequestNumber={pr.requestNumber}
              editable={isInProgress}
              onStaged={(completed) => {
                if (completed) onRefetch();
              }}
            />
            <Divider sx={{ mb: 2 }} />
          </>
        )}

        {/* Items table */}
        <Typography variant="h6" gutterBottom>
          Items ({pr.items.length})
        </Typography>

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
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Product Code</TableCell>
                      <TableCell>Hardware Category</TableCell>
                      <TableCell>Opening Number</TableCell>
                      {/* Shop-assembly pulls are per leaf too (#311), so a pair's two lines read
                          identically without this. */}
                      <TableCell>Leaf</TableCell>
                      <TableCell align="right">Requested Qty</TableCell>
                      {isPending && <TableCell align="right">Available Qty</TableCell>}
                      {isPending && <TableCell align="center">Status</TableCell>}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {looseItems.map((item) => {
                      const availableQty = getAvailableQty(item);
                      const sufficient = availableQty >= item.requestedQuantity;
                      return (
                        <TableRow key={item.id}>
                          <TableCell>{item.productCode ?? '-'}</TableCell>
                          <TableCell>{item.hardwareCategory ?? '-'}</TableCell>
                          <TableCell>{item.openingNumber}</TableCell>
                          <TableCell>{leafLabel(item.leaf) ?? '-'}</TableCell>
                          <TableCell align="right">{item.requestedQuantity}</TableCell>
                          {isPending && <TableCell align="right">{availableQty}</TableCell>}
                          {isPending && (
                            <TableCell align="center">
                              {sufficient ? (
                                <CheckCircleIcon color="success" fontSize="small" />
                              ) : (
                                <CancelIcon color="error" fontSize="small" />
                              )}
                            </TableCell>
                          )}
                        </TableRow>
                      );
                    })}
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
                <Table size="small">
                  <TableHead>
                    <TableRow>
                      <TableCell>Type</TableCell>
                      <TableCell>Opening Number</TableCell>
                      {/* #335: a pair ships as two lines. Without the leaf they read identically. */}
                      <TableCell>Leaf</TableCell>
                      <TableCell align="right">Requested Qty</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {openingItems.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell>Assembled Opening</TableCell>
                        <TableCell>{item.openingNumber}</TableCell>
                        <TableCell>{leafLabel(item.leaf) ?? '-'}</TableCell>
                        <TableCell align="right">{item.requestedQuantity}</TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </Box>
            )}
          </>
        )}
      </Modal>

      {/* Confirm: Approve */}
      <ConfirmDialog
        open={confirmApproveOpen}
        title="Approve Pull Request"
        message={`Approve and start processing Pull Request ${pr.requestNumber}? Inventory will be deducted.`}
        confirmLabel="Approve and Start"
        cancelLabel="Cancel"
        onConfirm={handleApprove}
        onCancel={() => setConfirmApproveOpen(false)}
      />

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
          able to show the server's blocker list without closing. */}
      <Modal
        open={cancelOpen}
        title={`Cancel ${pr.requestNumber}`}
        onClose={() => setCancelOpen(false)}
        maxWidth="sm"
        actions={
          <Stack direction="row" spacing={1}>
            <Button onClick={() => setCancelOpen(false)}>Keep pull</Button>
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
