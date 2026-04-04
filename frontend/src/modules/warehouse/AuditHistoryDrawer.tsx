import { useMemo } from 'react';
import {
  Drawer,
  Box,
  Typography,
  IconButton,
  CircularProgress,
  Alert,
  Chip,
  Divider,
} from '@mui/material';
import CloseIcon from '@mui/icons-material/Close';
import { useQuery } from '@apollo/client/react';
import { GET_AUDIT_LOG } from '../../graphql/queries';

interface AuditLogEntry {
  id: string;
  projectId: string | null;
  entityType: string;
  entityId: string;
  action: string;
  detail: Record<string, unknown> | null;
  performedBy: string;
  createdAt: string;
}

interface AuditHistoryDrawerProps {
  open: boolean;
  onClose: () => void;
  entityId: string;
  entityType: 'INVENTORY_LOCATION' | 'OPENING_ITEM';
  label?: string;
}

const ACTION_COLORS: Record<string, 'default' | 'primary' | 'secondary' | 'success' | 'warning' | 'error' | 'info'> = {
  RECEIVE: 'success',
  ADJUSTMENT: 'warning',
  MOVE: 'info',
  UNLOCATE: 'secondary',
  PUT_AWAY: 'primary',
  PULL_DEDUCTION: 'error',
  SPOT_CHECK: 'warning',
};

const ACTION_LABELS: Record<string, string> = {
  RECEIVE: 'Received',
  ADJUSTMENT: 'Qty Adjusted',
  MOVE: 'Moved',
  UNLOCATE: 'Unlocated',
  PUT_AWAY: 'Put Away',
  PULL_DEDUCTION: 'Pull Deduction',
  SPOT_CHECK: 'Spot Check',
};

function formatDateTime(dateStr: string): string {
  return new Date(dateStr).toLocaleString();
}

function formatLocation(loc: Record<string, unknown> | null | undefined): string {
  if (!loc) return '—';
  const { aisle, bay, bin } = loc as { aisle?: string; bay?: string; bin?: string };
  if (aisle && bay && bin) return `${aisle}-${bay}-${bin}`;
  return 'Unlocated';
}

function DetailLine({ label, value }: { label: string; value: string | number }) {
  return (
    <Typography variant="body2" color="text.secondary">
      {label}: <Typography component="span" variant="body2" color="text.primary">{value}</Typography>
    </Typography>
  );
}

function AuditEntry({ entry }: { entry: AuditLogEntry }) {
  const detail = entry.detail ?? {};

  const renderDetail = () => {
    switch (entry.action) {
      case 'ADJUSTMENT':
        return (
          <>
            <DetailLine label="Qty" value={`${detail.oldQuantity} → ${detail.newQuantity} (${(detail.adjustment as number) > 0 ? '+' : ''}${detail.adjustment})`} />
            {detail.reason && <DetailLine label="Reason" value={detail.reason as string} />}
          </>
        );
      case 'MOVE':
        return (
          <DetailLine
            label="Location"
            value={`${formatLocation(detail.fromLocation as Record<string, unknown>)} → ${formatLocation(detail.toLocation as Record<string, unknown>)}`}
          />
        );
      case 'UNLOCATE':
        return (
          <DetailLine label="From" value={formatLocation(detail.fromLocation as Record<string, unknown>)} />
        );
      case 'PUT_AWAY':
        return (
          <DetailLine label="To" value={formatLocation(detail.toLocation as Record<string, unknown>)} />
        );
      case 'RECEIVE':
        return (
          <>
            <DetailLine label="Qty" value={detail.quantity as number} />
            {detail.poNumber && <DetailLine label="PO" value={detail.poNumber as string} />}
            <DetailLine label="Location" value={formatLocation(detail.location as Record<string, unknown>)} />
          </>
        );
      case 'PULL_DEDUCTION':
        return (
          <>
            <DetailLine label="Qty" value={`${detail.oldQuantity} → ${detail.newQuantity} (-${detail.deducted})`} />
            {detail.pullRequestNumber && <DetailLine label="PR" value={detail.pullRequestNumber as string} />}
          </>
        );
      default:
        return null;
    }
  };

  return (
    <Box sx={{ py: 1.5 }}>
      <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 0.5 }}>
        <Chip
          label={ACTION_LABELS[entry.action] ?? entry.action}
          color={ACTION_COLORS[entry.action] ?? 'default'}
          size="small"
          variant="outlined"
        />
        <Typography variant="caption" color="text.secondary">
          {formatDateTime(entry.createdAt)}
        </Typography>
      </Box>
      <Box sx={{ ml: 0.5 }}>
        {renderDetail()}
        <Typography variant="caption" color="text.secondary">
          by {entry.performedBy}
        </Typography>
      </Box>
    </Box>
  );
}

export default function AuditHistoryDrawer({
  open,
  onClose,
  entityId,
  entityType,
  label,
}: AuditHistoryDrawerProps) {
  const { data, loading, error } = useQuery<{ auditLog: AuditLogEntry[] }>(GET_AUDIT_LOG, {
    variables: { entityId, entityType, limit: 50 },
    skip: !open,
    fetchPolicy: 'network-only',
  });

  const entries = useMemo(() => data?.auditLog ?? [], [data]);

  return (
    <Drawer anchor="right" open={open} onClose={onClose} PaperProps={{ sx: { width: 400, maxWidth: '90vw' } }}>
      <Box sx={{ p: 2 }}>
        <Box sx={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', mb: 2 }}>
          <Typography variant="h6">Audit History</Typography>
          <IconButton onClick={onClose} size="small">
            <CloseIcon />
          </IconButton>
        </Box>
        {label && (
          <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
            {label}
          </Typography>
        )}

        {loading && (
          <Box sx={{ display: 'flex', justifyContent: 'center', py: 4 }}>
            <CircularProgress size={24} />
          </Box>
        )}
        {error && <Alert severity="error">Error loading audit log: {error.message}</Alert>}
        {!loading && !error && entries.length === 0 && (
          <Alert severity="info">No audit history for this item</Alert>
        )}
        {!loading && entries.length > 0 && (
          <Box>
            {entries.map((entry, i) => (
              <Box key={entry.id}>
                <AuditEntry entry={entry} />
                {i < entries.length - 1 && <Divider />}
              </Box>
            ))}
          </Box>
        )}
      </Box>
    </Drawer>
  );
}
