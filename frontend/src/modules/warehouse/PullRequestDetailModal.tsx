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
  Divider,
} from '@mui/material';
import CheckCircleIcon from '@mui/icons-material/CheckCircle';
import CancelIcon from '@mui/icons-material/Cancel';
import { useMutation, useQuery } from '@apollo/client/react';
import { APPROVE_PULL_REQUEST, COMPLETE_PULL_REQUEST } from '../../graphql/mutations';
import { GET_INVENTORY_HIERARCHY } from '../../graphql/queries';
import { useRole } from '../../contexts/RoleContext';
import { useToast } from '../../components/Toast';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import type { PullRequest, PullRequestItem } from './PullRequestQueue';

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
}

interface InventoryCategoryGroup {
  hardwareCategory: string;
  totalQuantity: number;
  productCodes: InventoryProductCode[];
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
  const { role } = useRole();
  const { showToast } = useToast();

  // Confirm dialog state
  const [confirmApproveOpen, setConfirmApproveOpen] = useState(false);
  const [confirmCompleteOpen, setConfirmCompleteOpen] = useState(false);

  // Cancelled outcome dialog state
  const [cancelledDialogOpen, setCancelledDialogOpen] = useState(false);

  // Fetch inventory hierarchy for availability checks
  const { data: inventoryData } = useQuery<{ inventoryHierarchy: InventoryCategoryGroup[] }>(
    GET_INVENTORY_HIERARCHY,
    {
      variables: { projectId: pr.projectId },
      skip: pr.status !== 'PENDING',
    },
  );

  const inventoryHierarchy = inventoryData?.inventoryHierarchy ?? [];

  // Build lookup map: "category|productCode" -> available quantity
  const availabilityMap = useMemo(() => {
    const map = new Map<string, number>();
    for (const cat of inventoryHierarchy) {
      for (const pc of cat.productCodes) {
        const key = `${cat.hardwareCategory}|${pc.productCode}`;
        map.set(key, pc.totalQuantity);
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

  const [approvePR, { loading: approveLoading }] = useMutation(APPROVE_PULL_REQUEST, {
    onCompleted: (data) => {
      const outcome = (data as { approvePullRequest?: { outcome?: string } })?.approvePullRequest?.outcome;
      setConfirmApproveOpen(false);
      if (outcome === 'CANCELLED') {
        setCancelledDialogOpen(true);
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

  // --- Handlers ---

  const handleApprove = () => {
    approvePR({ variables: { id: pr.id, approvedBy: role ?? '' } });
  };

  const handleComplete = () => {
    completePR({ variables: { id: pr.id } });
  };

  const handleCancelledDialogClose = () => {
    setCancelledDialogOpen(false);
    onClose();
    onRefetch();
  };

  // --- Visibility rules ---

  const isPending = pr.status === 'PENDING';
  const isInProgress = pr.status === 'IN_PROGRESS';
  const isCompleted = pr.status === 'COMPLETED';
  const isCancelled = pr.status === 'CANCELLED';

  const isAssignedToCurrentUser = isInProgress && pr.assignedTo === role;
  const isLockedToOtherUser = isInProgress && pr.assignedTo !== role;

  // --- Action buttons ---

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
              This Pull Request was cancelled at {formatDateTime(pr.cancelledAt)}.
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

        {/* Insufficient inventory banner for pending PRs */}
        {isPending && !allLooseSufficient && looseItems.length > 0 && (
          <Alert severity="warning" sx={{ mb: 2 }}>
            Insufficient inventory — this PR will be auto-cancelled
          </Alert>
        )}

        {/* Locked to other user banner */}
        {isLockedToOtherUser && (
          <Alert severity="info" sx={{ mb: 2 }}>
            Locked to {pr.assignedTo}
          </Alert>
        )}

        <Divider sx={{ mb: 2 }} />

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
                      <TableCell align="right">Requested Qty</TableCell>
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {openingItems.map((item) => (
                      <TableRow key={item.id}>
                        <TableCell>Assembled Opening</TableCell>
                        <TableCell>{item.openingNumber}</TableCell>
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
        message={`Mark Pull Request ${pr.requestNumber} as pulled? This action cannot be undone.`}
        confirmLabel="Mark as Pulled"
        cancelLabel="Cancel"
        onConfirm={handleComplete}
        onCancel={() => setConfirmCompleteOpen(false)}
      />

      {/* Cancelled outcome dialog */}
      <ConfirmDialog
        open={cancelledDialogOpen}
        title="Pull Request Cancelled"
        message="Pull Request cancelled due to insufficient inventory. Originator has been notified."
        confirmLabel="OK"
        cancelLabel=""
        onConfirm={handleCancelledDialogClose}
        onCancel={handleCancelledDialogClose}
      />
    </>
  );
}
