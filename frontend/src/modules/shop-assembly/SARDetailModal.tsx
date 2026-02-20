import { useState } from 'react';
import {
  Box,
  Typography,
  Chip,
  Button,
  TextField,
  Divider,
  Stack,
  Table,
  TableHead,
  TableBody,
  TableRow,
  TableCell,
  Paper,
} from '@mui/material';
import { useMutation } from '@apollo/client/react';
import Modal from '../../components/Modal';
import ConfirmDialog from '../../components/ConfirmDialog';
import { useToast } from '../../components/Toast';
import { APPROVE_SHOP_ASSEMBLY_REQUEST, REJECT_SHOP_ASSEMBLY_REQUEST } from '../../graphql/mutations';
import type { ShopAssemblyRequest } from './SARListPage';

// --- Status chip colors ---

const STATUS_CHIP_COLOR: Record<string, 'default' | 'warning' | 'success' | 'error'> = {
  PENDING: 'warning',
  APPROVED: 'success',
  REJECTED: 'error',
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

interface SARDetailModalProps {
  open: boolean;
  sar: ShopAssemblyRequest;
  onClose: () => void;
  onRefetch: () => void;
}

// --- Component ---

export default function SARDetailModal({ open, sar, onClose, onRefetch }: SARDetailModalProps) {
  const { showToast } = useToast();

  // Confirm dialog state
  const [confirmApproveOpen, setConfirmApproveOpen] = useState(false);
  const [confirmRejectOpen, setConfirmRejectOpen] = useState(false);

  // Rejection reason state
  const [rejectionReason, setRejectionReason] = useState('');
  const [showRejectForm, setShowRejectForm] = useState(false);

  // --- Mutations ---

  const [approveSAR, { loading: approveLoading }] = useMutation(APPROVE_SHOP_ASSEMBLY_REQUEST, {
    onCompleted: (data) => {
      const prNumber = (data as { approveShopAssemblyRequest?: { pullRequest?: { requestNumber?: string } } })?.approveShopAssemblyRequest?.pullRequest?.requestNumber ?? '';
      showToast(
        `Shop Assembly Request approved. Pull Request ${prNumber} created.`,
        'success',
      );
      setConfirmApproveOpen(false);
      onRefetch();
      onClose();
    },
    onError: (error) => {
      setConfirmApproveOpen(false);
      showToast(error.message, 'error');
    },
  });

  const [rejectSAR, { loading: rejectLoading }] = useMutation(REJECT_SHOP_ASSEMBLY_REQUEST, {
    onCompleted: () => {
      showToast('Shop Assembly Request rejected', 'success');
      setConfirmRejectOpen(false);
      setShowRejectForm(false);
      setRejectionReason('');
      onRefetch();
      onClose();
    },
    onError: (error) => {
      setConfirmRejectOpen(false);
      showToast(error.message, 'error');
    },
  });

  // --- Handlers ---

  const handleApprove = () => {
    approveSAR({ variables: { id: sar.id } });
  };

  const handleRejectClick = () => {
    setShowRejectForm(true);
  };

  const handleRejectSubmit = () => {
    if (rejectionReason.trim().length === 0 || rejectionReason.length > 500) return;
    setConfirmRejectOpen(true);
  };

  const handleRejectConfirm = () => {
    rejectSAR({ variables: { id: sar.id, reason: rejectionReason.trim() } });
  };

  const handleCancelReject = () => {
    setShowRejectForm(false);
    setRejectionReason('');
  };

  // --- Visibility rules ---

  const isPending = sar.status === 'PENDING';
  const isApproved = sar.status === 'APPROVED';
  const isRejected = sar.status === 'REJECTED';

  // --- Action buttons ---

  const actionButtons = isPending ? (
    <Stack direction="row" spacing={1}>
      {showRejectForm ? (
        <>
          <Button onClick={handleCancelReject} disabled={rejectLoading}>
            Cancel
          </Button>
          <Button
            variant="contained"
            color="error"
            onClick={handleRejectSubmit}
            disabled={rejectLoading || rejectionReason.trim().length === 0 || rejectionReason.length > 500}
          >
            {rejectLoading ? 'Rejecting...' : 'Submit Rejection'}
          </Button>
        </>
      ) : (
        <>
          <Button
            variant="contained"
            color="primary"
            onClick={() => setConfirmApproveOpen(true)}
            disabled={approveLoading}
          >
            {approveLoading ? 'Approving...' : 'Approve Request'}
          </Button>
          <Button
            variant="outlined"
            color="error"
            onClick={handleRejectClick}
          >
            Reject Request
          </Button>
        </>
      )}
    </Stack>
  ) : undefined;

  // --- Render ---

  return (
    <>
      <Modal
        open={open}
        title={`SAR: ${sar.requestNumber}`}
        onClose={onClose}
        actions={actionButtons}
        maxWidth="md"
      >
        {/* Header: Status + Info */}
        <Box sx={{ mb: 2 }}>
          <Stack direction="row" spacing={2} alignItems="center" sx={{ mb: 1 }}>
            <Chip
              label={formatStatus(sar.status)}
              color={STATUS_CHIP_COLOR[sar.status] ?? 'default'}
              size="medium"
            />
          </Stack>
          <InfoRow label="Request #" value={sar.requestNumber} />
          <InfoRow label="Created Date" value={formatDate(sar.createdAt)} />
          <InfoRow label="Created By" value={sar.createdBy} />
        </Box>

        {/* Approval/Rejection Info */}
        {isApproved && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="success.main">
              Approved by: {sar.approvedBy ?? '-'} on {formatDateTime(sar.approvedAt)}
            </Typography>
          </Box>
        )}
        {isRejected && (
          <Box sx={{ mb: 2 }}>
            <Typography variant="body2" color="error.main">
              Rejected by: {sar.rejectedBy ?? '-'} on {formatDateTime(sar.rejectedAt)}.
              Reason: {sar.rejectionReason ?? '-'}
            </Typography>
          </Box>
        )}

        {/* Reject form (inline, before openings) */}
        {isPending && showRejectForm && (
          <Box sx={{ mb: 2 }}>
            <TextField
              label="Rejection Reason"
              value={rejectionReason}
              onChange={(e) => setRejectionReason(e.target.value)}
              multiline
              rows={3}
              fullWidth
              required
              error={rejectionReason.length > 500}
              helperText={`${rejectionReason.length}/500 characters`}
              slotProps={{ htmlInput: { maxLength: 500 } }}
            />
          </Box>
        )}

        <Divider sx={{ mb: 2 }} />

        {/* Openings List */}
        <Typography variant="h6" gutterBottom>
          Openings ({sar.openings.length})
        </Typography>

        {sar.openings.length === 0 ? (
          <Typography variant="body2" color="text.secondary">
            No openings in this request.
          </Typography>
        ) : (
          <Stack spacing={2}>
            {sar.openings.map((opening) => (
              <Paper key={opening.id} variant="outlined" sx={{ p: 2 }}>
                <Typography variant="subtitle1" fontWeight="bold" gutterBottom>
                  Opening: {opening.openingId}
                </Typography>
                {opening.items.length > 0 ? (
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Product Code</TableCell>
                        <TableCell>Hardware Category</TableCell>
                        <TableCell align="right">Quantity</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {opening.items.map((item) => (
                        <TableRow key={item.id}>
                          <TableCell>{item.productCode}</TableCell>
                          <TableCell>{item.hardwareCategory}</TableCell>
                          <TableCell align="right">{item.quantity}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                ) : (
                  <Typography variant="body2" color="text.secondary">
                    No hardware items.
                  </Typography>
                )}
              </Paper>
            ))}
          </Stack>
        )}
      </Modal>

      {/* Confirm: Approve */}
      <ConfirmDialog
        open={confirmApproveOpen}
        title="Approve Shop Assembly Request"
        message={`Approve this Shop Assembly Request? A Pull Request (PR-${sar.requestNumber}) will be created for the warehouse.`}
        confirmLabel="Approve"
        cancelLabel="Cancel"
        onConfirm={handleApprove}
        onCancel={() => setConfirmApproveOpen(false)}
      />

      {/* Confirm: Reject */}
      <ConfirmDialog
        open={confirmRejectOpen}
        title="Reject Shop Assembly Request"
        message={`Reject this Shop Assembly Request with reason: "${rejectionReason.trim()}"?`}
        confirmLabel="Reject"
        cancelLabel="Cancel"
        onConfirm={handleRejectConfirm}
        onCancel={() => setConfirmRejectOpen(false)}
      />
    </>
  );
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
